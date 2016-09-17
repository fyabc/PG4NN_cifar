#! /usr/bin/python

from __future__ import print_function, unicode_literals

import sys
import os
from functools import wraps
import random
import time
import cPickle as pkl
import numpy as np
# from theano import config

from config import Config, ParamConfig, IMDBConfig

__author__ = 'fyabc'

# fX = config.floatX
fX = Config['floatX']

logging_file = sys.stderr

_depth = 0


def logging(func, file_=sys.stderr):
    @wraps(func)
    def wrapper(*args, **kwargs):
        global _depth

        print(' ' * 2 * _depth + '[Start function %s...]' % func.__name__, file=file_)
        _depth += 1
        start_time = time.time()

        result = func(*args, **kwargs)

        end_time = time.time()
        _depth -= 1
        print(' ' * 2 * _depth + '[Function %s done, time: %.3fs]' % (func.__name__, end_time - start_time), file=file_)
        return result
    return wrapper


def message(*args, **kwargs):
    print(*args, file=logging_file, **kwargs)


def floatX(value):
    return np.asarray(value, dtype=fX)


def init_norm(*dims):
    return floatX(np.random.randn(*dims))


def unpickle(filename):
    with open(filename, 'rb') as f:
        return pkl.load(f)


###############################
# Data loading and processing #
###############################

@logging
def load_cifar10_data(data_dir=Config['data_dir']):
    if not os.path.exists(data_dir):
        raise Exception("CIFAR-10 dataset can not be found. Please download the dataset from "
                        "'https://www.cs.toronto.edu/~kriz/cifar.html'.")

    train_size = Config['train_size']

    xs = []
    ys = []
    for j in range(5):
        d = unpickle(data_dir + '/data_batch_%d' % (j + 1))
        xs.append(d['data'])
        ys.append(d['labels'])

    d = unpickle(data_dir + '/test_batch')
    xs.append(d['data'])
    ys.append(d['labels'])

    x = np.concatenate(xs) / np.float32(255)
    y = np.concatenate(ys)
    x = np.dstack((x[:, :1024], x[:, 1024:2048], x[:, 2048:]))
    x = x.reshape((x.shape[0], 32, 32, 3)).transpose(0, 3, 1, 2)

    # subtract per-pixel mean
    pixel_mean = np.mean(x[0:train_size], axis=0)
    # pickle.dump(pixel_mean, open("cifar10-pixel_mean.pkl","wb"))
    x -= pixel_mean

    # create mirrored images
    x_train = x[0:train_size, :, :, :]
    y_train = y[0:train_size]
    x_train_flip = x_train[:, :, :, ::-1]
    y_train_flip = y_train
    x_train = np.concatenate((x_train, x_train_flip), axis=0)
    y_train = np.concatenate((y_train, y_train_flip), axis=0)

    x_test = x[train_size:, :, :, :]
    y_test = y[train_size:]

    return {
        'x_train': floatX(x_train),
        'y_train': y_train.astype('int32'),
        'x_test': floatX(x_test),
        'y_test': y_test.astype('int32')
    }


def split_cifar10_data(data):
    x_train = data['x_train']
    y_train = data['y_train']
    x_test = data['x_test']
    y_test = data['y_test']

    # One: validate is not part of train
    x_validate = x_test[:Config['validation_size']]
    y_validate = y_test[:Config['validation_size']]
    x_test = x_test[-Config['test_size']:]
    y_test = y_test[-Config['test_size']:]

    # # Another: validate is part of train
    # x_validate = x_train[:Config['validation_size']]
    # y_validate = y_train[:Config['validation_size']]

    return x_train, y_train, x_validate, y_validate, x_test, y_test


def get_small_train_data(x_train, y_train, train_small_size=None):
    train_small_size = train_small_size or ParamConfig['train_epoch_size']

    train_size = x_train.shape[0]

    # Use small dataset to check the code
    sampled_indices = random.sample(range(train_size), train_small_size)
    return x_train[sampled_indices], y_train[sampled_indices]


def shuffle_data(x_train, y_train):
    shuffled_indices = np.arange(y_train.shape[0])
    np.random.shuffle(shuffled_indices)
    return x_train[shuffled_indices], y_train[shuffled_indices]


@logging
def load_imdb_data(data_dir=None, n_words=100000, valid_portion=0.1, maxlen=None, sort_by_len=True):
    """Loads the dataset

    :type data_dir: String
    :param data_dir: The path to the dataset (here IMDB)
    :type n_words: int
    :param n_words: The number of word to keep in the vocabulary.
        All extra words are set to unknown (1).
    :type valid_portion: float
    :param valid_portion: The proportion of the full train set used for
        the validation set.
    :type maxlen: None or positive int
    :param maxlen: the max sequence length we use in the train/valid set.
    :type sort_by_len: bool
    :name sort_by_len: Sort by the sequence length for the train,
        valid and test set. This allow faster execution as it cause
        less padding per minibatch. Another mechanism must be used to
        shuffle the train set at each epoch.
    """

    data_dir = data_dir or IMDBConfig['data_dir']

    import gzip
    if data_dir.endswith(".gz"):
        f = gzip.open(data_dir, 'rb')
    else:
        f = open(data_dir, 'rb')

    train_set = pkl.load(f)
    test_set = pkl.load(f)
    f.close()

    if maxlen:
        new_train_set_x = []
        new_train_set_y = []
        for x, y in zip(train_set[0], train_set[1]):
            if len(x) < maxlen:
                new_train_set_x.append(x)
                new_train_set_y.append(y)
        train_set = (new_train_set_x, new_train_set_y)
        del new_train_set_x, new_train_set_y

    # split training set into validation set
    train_set_x, train_set_y = train_set
    n_samples = len(train_set_x)
    sidx = np.random.permutation(n_samples)
    n_train = int(np.round(n_samples * (1. - valid_portion)))
    valid_set_x = [train_set_x[s] for s in sidx[n_train:]]
    valid_set_y = [train_set_y[s] for s in sidx[n_train:]]
    train_set_x = [train_set_x[s] for s in sidx[:n_train]]
    train_set_y = [train_set_y[s] for s in sidx[:n_train]]

    train_set = (train_set_x, train_set_y)
    valid_set = (valid_set_x, valid_set_y)

    def remove_unk(x):
        return [[1 if w >= n_words else w for w in sen] for sen in x]

    test_set_x, test_set_y = test_set
    valid_set_x, valid_set_y = valid_set
    train_set_x, train_set_y = train_set

    train_set_x = remove_unk(train_set_x)
    valid_set_x = remove_unk(valid_set_x)
    test_set_x = remove_unk(test_set_x)

    def len_argsort(seq):
        return sorted(range(len(seq)), key=lambda x: len(seq[x]))

    if sort_by_len:
        sorted_index = len_argsort(test_set_x)
        test_set_x = [test_set_x[i] for i in sorted_index]
        test_set_y = [test_set_y[i] for i in sorted_index]

        sorted_index = len_argsort(valid_set_x)
        valid_set_x = [valid_set_x[i] for i in sorted_index]
        valid_set_y = [valid_set_y[i] for i in sorted_index]

        sorted_index = len_argsort(train_set_x)
        train_set_x = [train_set_x[i] for i in sorted_index]
        train_set_y = [train_set_y[i] for i in sorted_index]

    train_data = (train_set_x, train_set_y)
    valid_data = (valid_set_x, valid_set_y)
    test_data = (test_set_x, test_set_y)

    return train_data, valid_data, test_data


@logging
def preprocess_imdb_data(train_data, valid_data, test_data):
    train_x, train_y = train_data
    test_x, test_y = test_data

    test_size = IMDBConfig['test_size']
    if test_size > 0:
        # The test set is sorted by size, but we want to keep random
        # size example.  So we must select a random selection of the
        # examples.
        idx = np.arange(len(test_x))
        np.random.shuffle(idx)
        idx = idx[:test_size]
        test_data = ([test_x[n] for n in idx], [test_y[n] for n in idx])

    ydim = np.max(train_y) + 1

    IMDBConfig['ydim'] = ydim

    return train_data, valid_data, test_data


def prepare_imdb_data(seqs, labels, maxlen=None):
    """Create the matrices from the datasets.

    This pad each sequence to the same length: the length of the
    longest sequence or maxlen.

    if maxlen is set, we will cut all sequence to this maximum
    length.

    This swap the axis!
    """

    # x: a list of sentences
    lengths = [len(s) for s in seqs]

    if maxlen is not None:
        new_seqs = []
        new_labels = []
        new_lengths = []
        for l, s, y in zip(lengths, seqs, labels):
            if l < maxlen:
                new_seqs.append(s)
                new_labels.append(y)
                new_lengths.append(l)
        lengths = new_lengths
        labels = new_labels
        seqs = new_seqs

        if len(lengths) < 1:
            return None, None, None

    n_samples = len(seqs)
    maxlen = np.max(lengths)

    x = np.zeros((maxlen, n_samples)).astype('int64')
    x_mask = np.zeros((maxlen, n_samples)).astype(fX)
    for idx, s in enumerate(seqs):
        x[:lengths[idx], idx] = s
        x_mask[:lengths[idx], idx] = 1.

    return x, x_mask, labels


##############################
# Other utilities of CIFAR10 #
##############################

def iterate_minibatches(inputs, targets, batch_size, shuffle=False, augment=False):
    assert len(inputs) == len(targets)
    if shuffle:
        indices = np.arange(len(inputs))
        np.random.shuffle(indices)

    for start_idx in range(0, len(inputs) - batch_size + 1, batch_size):
        if shuffle:
            excerpt = indices[start_idx:start_idx + batch_size]
        else:
            excerpt = slice(start_idx, start_idx + batch_size)
        if augment:
            # as in paper :
            # pad feature arrays with 4 pixels on each side
            # and do random cropping of 32x32
            padded = np.pad(inputs[excerpt], ((0, 0), (0, 0), (4, 4), (4, 4)), mode=str('constant'))
            random_cropped = np.zeros(inputs[excerpt].shape, dtype=np.float32)
            crops = np.random.random_integers(0, high=8, size=(batch_size, 2))

            for r in range(batch_size):
                random_cropped[r, :, :, :] = padded[r, :, crops[r, 0]:(crops[r, 0] + 32),
                                                    crops[r, 1]:(crops[r, 1] + 32)]
            inp_exc = random_cropped
        else:
            inp_exc = inputs[excerpt]

        yield inp_exc, targets[excerpt]


###########################
# Other utilities of IMDB #
###########################

def get_minibatches_idx(n, minibatch_size, shuffle=False):
    """
    Used to shuffle the dataset at each iteration.
    """

    idx_list = np.arange(n, dtype="int32")

    if shuffle:
        np.random.shuffle(idx_list)

    minibatches = []
    minibatch_start = 0
    for i in range(n // minibatch_size):
        minibatches.append(idx_list[minibatch_start:
                                    minibatch_start + minibatch_size])
        minibatch_start += minibatch_size

    if minibatch_start != n:
        # Make a minibatch out of what is left
        minibatches.append(idx_list[minibatch_start:])

    return list(enumerate(minibatches))


########################################
# Simple command line arguments parser #
########################################

def simple_parse_args(args):
    args_dict = {}
    param_args_dict = {}

    for arg in args:
        arg = arg.replace('@', '"')

        if '=' in arg:
            if arg[0] == '%':
                arg = arg[1:]
                the_dict = args_dict
                target_dict = Config
            else:
                the_dict = param_args_dict
                target_dict = ParamConfig
            key, value = arg.split('=')
            if key not in target_dict:
                raise Exception('The key {} is not in the parameters.'.format(key))

            the_dict[key] = eval(value)

    return args_dict, param_args_dict


def process_before_train(param_config=ParamConfig):
    import pprint

    if '-h' in sys.argv or '--help' in sys.argv:
        print('Usage: add properties just like this:\n'
              '    add_label_prob=False\n'
              '    %policy_save_freq=10\n'
              '\n'
              'properties starts with % are in Config, other properties are in ParamConfig.')

    args_dict, param_args_dict = simple_parse_args(sys.argv)
    Config.update(args_dict)
    param_config.update(param_args_dict)

    message('The configures and hyperparameters are:')
    pprint.pprint(Config, stream=sys.stderr)


def test():
    train_data, valid_data, test_data = load_imdb_data()
    train_x, train_y = train_data
    valid_x, valid_y = valid_data
    test_x, test_y = test_data

    print('Train:', np.asarray(train_x).shape, np.asarray(train_y).shape)
    print('Valid:', np.asarray(valid_x).shape, np.asarray(valid_y).shape)
    print('Test:', np.asarray(test_x).shape, np.asarray(test_y).shape)

    for i in range(20):
        print(train_x[i], train_y[i])


if __name__ == '__main__':
    test()
