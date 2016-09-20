#! /usr/bin/python

from __future__ import print_function, unicode_literals

import time
import numpy as np
import cPickle as pkl
from collections import OrderedDict

import theano.tensor as T
import theano
from theano.sandbox.rng_mrg import MRG_RandomStreams as RandomStreams

from utils import fX, floatX, logging, message
from utils_IMDB import prepare_imdb_data as prepare_data, pr, ortho_weight, get_minibatches_idx
from optimizers import adadelta, adam, sgd, rmsprop
from config import IMDBConfig

__author__ = 'fyabc'


class IMDBModel(object):
    def __init__(self, reload_model=False):
        self.train_batch_size = IMDBConfig['train_batch_size']
        self.validate_batch_size = IMDBConfig['validate_batch_size']
        self.learning_rate = floatX(IMDBConfig['learning_rate'])

        # Parameters of the model (Theano shared variables)
        self.parameters = OrderedDict()

        # Build train function and parameters
        self.use_noise = None
        self.inputs = None
        self.mask = None
        self.targets = None
        self.cost = None

        self.f_cost = None
        self.f_grad = None
        self.f_predict = None
        self.f_predict_prob = None
        self.f_grad_shared = None
        self.f_update = None

        self.build_train_function()

        if reload_model:
            self.load_model()

    def init_parameters(self):
        np_parameters = OrderedDict()

        rands = np.random.rand(IMDBConfig['n_words'], IMDBConfig['dim_proj'])

        # embedding
        np_parameters['Wemb'] = (0.01 * rands).astype(fX)

        # LSTM
        self.init_lstm_parameters(np_parameters)

        # classifier
        np_parameters['U'] = 0.01 * np.random.randn(IMDBConfig['dim_proj'], IMDBConfig['ydim']).astype(fX)
        np_parameters['b'] = np.zeros((IMDBConfig['ydim'],)).astype(fX)

        # numpy parameters to shared variables
        for key, value in np_parameters.iteritems():
            self.parameters[key] = theano.shared(value, name=key)

    @staticmethod
    def init_lstm_parameters(np_parameters):
        prefix = 'lstm'
        W = np.concatenate([ortho_weight(IMDBConfig['dim_proj']),
                            ortho_weight(IMDBConfig['dim_proj']),
                            ortho_weight(IMDBConfig['dim_proj']),
                            ortho_weight(IMDBConfig['dim_proj'])], axis=1)
        np_parameters[pr(prefix, 'W')] = W
        U = np.concatenate([ortho_weight(IMDBConfig['dim_proj']),
                            ortho_weight(IMDBConfig['dim_proj']),
                            ortho_weight(IMDBConfig['dim_proj']),
                            ortho_weight(IMDBConfig['dim_proj'])], axis=1)
        np_parameters[pr(prefix, 'U')] = U
        b = np.zeros((4 * IMDBConfig['dim_proj'],))
        np_parameters[pr(prefix, 'b')] = b.astype(fX)

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

            i = T.nnet.sigmoid(_slice(preact, 0, IMDBConfig['dim_proj']))
            f = T.nnet.sigmoid(_slice(preact, 1, IMDBConfig['dim_proj']))
            o = T.nnet.sigmoid(_slice(preact, 2, IMDBConfig['dim_proj']))
            c = T.tanh(_slice(preact, 3, IMDBConfig['dim_proj']))

            c = f * c_ + i * c
            c = m_[:, None] * c + (1. - m_)[:, None] * c_

            h = o * T.tanh(c)
            h = m_[:, None] * h + (1. - m_)[:, None] * h_

            return h, c

        state_below = (T.dot(state_below, self.parameters[pr(prefix, 'W')]) +
                       self.parameters[pr(prefix, 'b')])

        dim_proj = IMDBConfig['dim_proj']
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
        theano.config.exception_verbosity = 'high'
        theano.config.optimizer = 'None'

        # Initialize self.parameters
        self.init_parameters()

        trng = RandomStreams(IMDBConfig['seed'])

        # Build Theano tensor variables.

        # Used for dropout.
        self.use_noise = theano.shared(floatX(0.))

        self.inputs = T.matrix('inputs', dtype='int64')
        self.mask = T.matrix('mask', dtype=fX)
        self.targets = T.vector('targets', dtype='int64')

        n_timesteps = self.inputs.shape[0]
        n_samples = self.inputs.shape[1]

        emb = self.parameters['Wemb'][self.inputs.flatten()].reshape([n_timesteps, n_samples, IMDBConfig['dim_proj']])

        proj = self.lstm_layer(emb, self.mask)

        proj = (proj * self.mask[:, :, None]).sum(axis=0)
        proj = proj / self.mask.sum(axis=0)[:, None]

        if IMDBConfig['use_dropout']:
            proj = self.dropout_layer(proj, self.use_noise, trng)
            
        predict = T.nnet.softmax(T.dot(proj, self.parameters['U']) + self.parameters['b'])

        self.f_predict_prob = theano.function([self.inputs, self.mask], predict, name='f_pred_prob')
        self.f_predict = theano.function([self.inputs, self.mask], predict.argmax(axis=1), name='f_pred')
    
        off = 1e-8
        if predict.dtype == 'float16':
            off = 1e-6
    
        self.cost = -T.log(predict[T.arange(n_samples), self.targets] + off).mean()

        # return self.use_noise, self.inputs, self.mask, self.targets, self.f_predict_prob, self.f_predict, self.cost

        decay_c = IMDBConfig['decay_c']
        if decay_c > 0.:
            decay_c = theano.shared(floatX(decay_c), name='decay_c')
            weight_decay = 0.
            weight_decay += (self.parameters['U'] ** 2).sum()
            weight_decay *= decay_c
            self.cost += weight_decay

        self.f_cost = theano.function([self.inputs, self.mask, self.targets], self.cost, name='f_cost')

        grads = T.grad(self.cost, wrt=list(self.parameters.values()))
        self.f_grad = theano.function([self.inputs, self.mask, self.targets], grads, name='f_grad')

        lr = T.scalar('lr', dtype=fX)
        self.f_grad_shared, self.f_update = eval(IMDBConfig['optimizer'])(
            lr, self.parameters, grads, [self.inputs, self.mask, self.targets], self.cost)

    @logging
    def load_model(self, filename=None):
        filename = filename or IMDBConfig['save_to']

    @logging
    def save_model(self, filename=None):
        filename = filename or IMDBConfig['save_to']

    def predict_error(self, data_x, data_y, batch_indices, verbose=False):
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


def test():
    IMDBConfig['ydim'] = 2
    model = IMDBModel()


if __name__ == '__main__':
    test()
