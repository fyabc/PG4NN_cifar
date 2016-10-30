#! /usr/bin/python

from __future__ import print_function, unicode_literals

import time
import numpy as np
import cPickle as pkl
from collections import OrderedDict

import theano.tensor as T
import theano
from theano.sandbox.rng_mrg import MRG_RandomStreams as RandomStreams

from utils import fX, floatX, logging, message, average, get_minibatches_idx
from utils_IMDB import prepare_imdb_data as prepare_data, pr, ortho_weight
from optimizers import adadelta, adam, sgd, rmsprop
from config import IMDBConfig as ParamConfig, PolicyConfig

__author__ = 'fyabc'


class IMDBModelBase(object):

    output_size = 2

    def __init__(self,
                 train_batch_size=None,
                 validate_batch_size=None
                 ):
        # Functions and parameters that must be provided.
        self.train_batch_size = train_batch_size or ParamConfig['train_batch_size']
        self.validate_batch_size = validate_batch_size or ParamConfig['validate_batch_size']

        self.learning_rate = None

        self.f_probs = None
        self.f_cost_list_without_decay = None
        self.f_cost_without_decay = None
        self.f_cost = None

    def reset_parameters(self):
        pass

    def save_model(self, filename=None):
        pass

    def load_model(self, filename=None):
        pass

    def f_train(self, x, mask, y):
        pass

    def get_training_loss(self, x_train, y_train):
        pass

    @staticmethod
    def get_policy_input_size():
        input_size = 2

        if PolicyConfig['add_label_input']:
            input_size += 1
        if PolicyConfig['add_label']:
            # input_size += 1
            input_size += 2
        if PolicyConfig['use_first_layer_output']:
            input_size += 16 * 32 * 32
        if PolicyConfig['add_epoch_number']:
            input_size += 1
        if PolicyConfig['add_learning_rate']:
            input_size += 1
        if PolicyConfig['add_margin']:
            input_size += 1
        if PolicyConfig['add_average_accuracy']:
            input_size += 1
        return input_size

    def get_policy_input(self, x, mask, y, epoch, history_accuracy=None):
        batch_size = y.shape[0]

        probability = self.f_probs(x, mask)

        if PolicyConfig['add_label_input']:
            label_inputs = np.zeros(shape=(batch_size, 1), dtype=fX)
            for i in range(batch_size):
                # assert probability[i, targets[i]] > 0, 'Probability <= 0!!!'
                label_inputs[i, 0] = np.log(max(probability[i, y[i]], 1e-9))
            probability = np.hstack([probability, label_inputs])

        if PolicyConfig['add_label']:
            # labels = floatX(targets) * (1.0 / ParamConfig['cnn_output_size'])
            # probability = np.hstack([probability, labels[:, None]])

            labels = np.zeros(shape=(batch_size, self.output_size), dtype=fX)
            for i, target in enumerate(y):
                labels[i, target] = 1.

            probability = np.hstack([probability, labels])

        # TODO add first layer output here
        if PolicyConfig['use_first_layer_output']:
            pass

        if PolicyConfig['add_epoch_number']:
            epoch_number_inputs = np.full((batch_size, 1), floatX(epoch) / ParamConfig['epoch_per_episode'], dtype=fX)
            probability = np.hstack([probability, epoch_number_inputs])

        if PolicyConfig['add_learning_rate']:
            learning_rate_inputs = np.full((batch_size, 1), self.learning_rate, dtype=fX)
            probability = np.hstack([probability, learning_rate_inputs])

        if PolicyConfig['add_margin']:
            margin_inputs = np.zeros(shape=(batch_size, 1), dtype=fX)
            for i in range(batch_size):
                prob_i = probability[i].copy()
                margin_inputs[i, 0] = prob_i[y[i]]
                prob_i[y[i]] = -np.inf

                margin_inputs[i, 0] -= np.max(prob_i)
            probability = np.hstack([probability, margin_inputs])

        if PolicyConfig['add_average_accuracy']:
            avg_acc_inputs = np.full((batch_size, 1), average(history_accuracy), dtype=fX)
            probability = np.hstack([probability, avg_acc_inputs])

        return probability


class IMDBModel(IMDBModelBase):

    output_size = 2

    def __init__(self,
                 reload_model=False,
                 train_batch_size=None,
                 validate_batch_size=None,
                 ):
        super(IMDBModel, self).__init__(train_batch_size, validate_batch_size)

        self.learning_rate = floatX(ParamConfig['learning_rate'])

        # Parameters of the model (Theano shared variables)
        self.parameters = OrderedDict()
        self.np_parameters = OrderedDict()

        self.build_train_function()

        if reload_model:
            self.load_model()

    def init_parameters(self):
        rands = np.random.rand(ParamConfig['n_words'], ParamConfig['dim_proj'])

        # embedding
        self.np_parameters['Wemb'] = (0.01 * rands).astype(fX)

        # LSTM
        self.init_lstm_parameters()

        # classifier
        self.np_parameters['U'] = 0.01 * np.random.randn(ParamConfig['dim_proj'], ParamConfig['ydim']).astype(fX)
        self.np_parameters['b'] = np.zeros((ParamConfig['ydim'],)).astype(fX)

        # numpy parameters to shared variables
        for key, value in self.np_parameters.iteritems():
            self.parameters[key] = theano.shared(value, name=key)

    def init_lstm_parameters(self):
        prefix = 'lstm'
        W = np.concatenate([ortho_weight(ParamConfig['dim_proj']),
                            ortho_weight(ParamConfig['dim_proj']),
                            ortho_weight(ParamConfig['dim_proj']),
                            ortho_weight(ParamConfig['dim_proj'])], axis=1)
        self.np_parameters[pr(prefix, 'W')] = W
        U = np.concatenate([ortho_weight(ParamConfig['dim_proj']),
                            ortho_weight(ParamConfig['dim_proj']),
                            ortho_weight(ParamConfig['dim_proj']),
                            ortho_weight(ParamConfig['dim_proj'])], axis=1)
        self.np_parameters[pr(prefix, 'U')] = U
        b = np.zeros((4 * ParamConfig['dim_proj'],))
        self.np_parameters[pr(prefix, 'b')] = b.astype(fX)

    def reset_parameters(self):
        for key, value in self.np_parameters.iteritems():
            self.parameters[key].set_value(value)

    def lstm_layer(self, state_below, mask):
        prefix = 'lstm'

        nsteps = state_below.shape[0]
        if state_below.ndim == 3:
            n_samples = state_below.shape[1]
        else:
            n_samples = 1

        assert mask is not None

        def _slice(_x, n, dim):
            if _x.ndim == 3:
                return _x[:, :, n * dim:(n + 1) * dim]
            return _x[:, n * dim:(n + 1) * dim]

        def _step(m_, x_, h_, c_):
            preact = T.dot(h_, self.parameters[pr(prefix, 'U')])
            preact += x_

            i = T.nnet.sigmoid(_slice(preact, 0, ParamConfig['dim_proj']))
            f = T.nnet.sigmoid(_slice(preact, 1, ParamConfig['dim_proj']))
            o = T.nnet.sigmoid(_slice(preact, 2, ParamConfig['dim_proj']))
            c = T.tanh(_slice(preact, 3, ParamConfig['dim_proj']))

            c = f * c_ + i * c
            c = m_[:, None] * c + (1. - m_)[:, None] * c_

            h = o * T.tanh(c)
            h = m_[:, None] * h + (1. - m_)[:, None] * h_

            return h, c

        state_below = (T.dot(state_below, self.parameters[pr(prefix, 'W')]) +
                       self.parameters[pr(prefix, 'b')])

        dim_proj = ParamConfig['dim_proj']
        rval, updates = theano.scan(
                _step,
                sequences=[mask, state_below],
                outputs_info=[T.alloc(floatX(0.),
                                      n_samples,
                                      dim_proj),
                              T.alloc(floatX(0.),
                                      n_samples,
                                      dim_proj)],
                name=pr(prefix, '_layers'),
                n_steps=nsteps
        )

        return rval[0]

    @staticmethod
    def dropout_layer(state_before, use_noise, trng):
        proj = T.switch(
            use_noise,
            (state_before *
             trng.binomial(state_before.shape,
                           p=0.5, n=1,
                           dtype=state_before.dtype)),
            state_before * 0.5
        )
        return proj

    @logging
    def build_train_function(self):
        # theano.config.exception_verbosity = 'high'
        # theano.config.optimizer = 'None'

        # Initialize self.parameters
        self.init_parameters()

        trng = RandomStreams(ParamConfig['seed'])

        # Build Theano tensor variables.

        # Used for dropout.
        self.use_noise = theano.shared(floatX(0.))

        self.inputs = T.matrix('inputs', dtype='int64')
        self.mask = T.matrix('mask', dtype=fX)
        self.targets = T.vector('targets', dtype='int64')

        n_timesteps = self.inputs.shape[0]
        n_samples = self.inputs.shape[1]

        emb = self.parameters['Wemb'][self.inputs.flatten()].reshape([n_timesteps, n_samples, ParamConfig['dim_proj']])

        proj = self.lstm_layer(emb, self.mask)

        proj = (proj * self.mask[:, :, None]).sum(axis=0)
        proj = proj / self.mask.sum(axis=0)[:, None]

        if ParamConfig['use_dropout']:
            proj = self.dropout_layer(proj, self.use_noise, trng)
            
        predict = T.nnet.softmax(T.dot(proj, self.parameters['U']) + self.parameters['b'])

        self.f_probs = theano.function([self.inputs, self.mask], predict, name='f_pred_prob')
        self.f_predict = theano.function([self.inputs, self.mask], predict.argmax(axis=1), name='f_pred')
    
        off = 1e-8
        if predict.dtype == 'float16':
            off = 1e-6

        cost_list = -T.log(predict[T.arange(n_samples), self.targets] + off)
        self.f_cost_list_without_decay = theano.function(
            [self.inputs, self.mask, self.targets], cost_list, name='f_cost_list_without_decay'
        )
    
        cost = cost_list.mean()

        self.f_cost_without_decay = theano.function(
            [self.inputs, self.mask, self.targets], cost, name='f_cost_without_decay'
        )

        decay_c = ParamConfig['decay_c']
        if decay_c > 0.:
            decay_c = theano.shared(floatX(decay_c), name='decay_c')
            weight_decay = 0.
            weight_decay += (self.parameters['U'] ** 2).sum()
            weight_decay *= decay_c
            cost += weight_decay

        self.f_cost = theano.function([self.inputs, self.mask, self.targets], cost, name='f_cost')

        grads = T.grad(cost, wrt=list(self.parameters.values()))
        self.f_grad = theano.function([self.inputs, self.mask, self.targets], grads, name='f_grad')

        lr = T.scalar('lr', dtype=fX)
        self.f_grad_shared, self.f_update = eval(ParamConfig['optimizer'])(
            lr, self.parameters, grads, [self.inputs, self.mask, self.targets], cost)

    def f_train(self, x, mask, y):
        if x.shape[1] == 0:
            return None

        cost = self.f_grad_shared(x, mask, y)
        self.f_update(self.learning_rate)

        return cost

    @logging
    def load_model(self, filename=None):
        filename = filename or ParamConfig['save_to']

    @logging
    def save_model(self, filename=None):
        filename = filename or ParamConfig['save_to']

    def predict_error(self, data_x, data_y, batch_indices):
        """
        Just compute the error
        f_pred: Theano fct computing the prediction
        prepare_data: usual prepare_data for that dataset.
        """

        valid_err = 0
        for _, valid_index in batch_indices:
            x, mask, y = prepare_data([data_x[t] for t in valid_index],
                                      np.array(data_y)[valid_index],
                                      maxlen=None)
            predicts = self.f_predict(x, mask)
            targets = np.array(data_y)[valid_index]
            valid_err += (predicts == targets).sum()
        valid_err = 1. - floatX(valid_err) / len(data_x)

        return valid_err

    def get_parameter_values(self):
        result = OrderedDict()
        for key in self.parameters:
            result[key] = self.parameters[key].get_value()
        return result

    def get_training_loss(self, x_train, y_train):
        sum_loss = 0.0
        kf = get_minibatches_idx(len(y_train), self.train_batch_size, shuffle=False)

        for _, train_index in kf:
            self.use_noise.set_value(floatX(1.))

            x = [x_train[t] for t in train_index]
            y = [y_train[t] for t in train_index]

            x, mask, y = prepare_data(x, np.asarray(y, dtype='int64'))

            sum_loss += self.f_cost(x, mask, y)

        return sum_loss / len(kf)


def test():
    ParamConfig['ydim'] = 2
    model = IMDBModel()


if __name__ == '__main__':
    test()
