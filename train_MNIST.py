#! /usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import sys
import heapq
import traceback
from collections import deque

import numpy as np

from config import Config, MNISTConfig as ParamConfig, PolicyConfig
from utils import *
from utils_MNIST import load_mnist_data
from model_MNIST import MNISTModel
from policyNetwork import LRPolicyNetwork
from criticNetwork import CriticNetwork
from batch_updater import *

__author__ = 'fyabc'


def pre_process_data():
    # Load the dataset
    x_train, y_train, x_validate, y_validate, x_test, y_test = load_mnist_data()

    train_size, validate_size, test_size = y_train.shape[0], y_validate.shape[0], y_test.shape[0]

    message('Training data size:', train_size)
    message('Validation data size:', validate_size)
    message('Test data size:', test_size)

    return x_train, y_train, x_validate, y_validate, x_test, y_test, train_size, validate_size, test_size


def pre_process_config(model, train_size):
    # Some hyperparameters
    # early-stopping parameters
    # look as this many examples regardless
    patience = ParamConfig['patience']
    # wait this much longer when a new best is found
    patience_increase = ParamConfig['patience_increase']
    # a relative improvement of this much is considered significant
    improvement_threshold = ParamConfig['improvement_threshold']

    # go through this many minibatches before checking the network
    # on the validation set; in this case we check every epoch
    # validation_frequency = min(train_size // model.train_batch_size, patience // 2)
    validation_frequency = ParamConfig['valid_freq']

    return patience, patience_increase, improvement_threshold, validation_frequency


def validate_point_message(model, x_train, y_train, x_validate, y_validate, x_test, y_test,
                           history_train_loss, train_batches, total_accepted_cases, epoch, iteration,
                           validate_point_number):
    # Get training loss
    train_loss = model.get_training_loss(x_train, y_train)

    # Get validation loss and accuracy
    validate_loss, validate_acc, validate_batches = model.validate_or_test(x_validate, y_validate)
    validate_loss /= validate_batches
    validate_acc /= validate_batches

    message('Validate Point: Epoch {} Iteration {}'.format(epoch, iteration))
    message('Training Loss:', train_loss)
    message('History Training Loss:', history_train_loss / train_batches)
    message('Validate Loss:', validate_loss)
    message('#Validate accuracy:', validate_acc)

    if ParamConfig['test_per_point'] > 0 and validate_point_number % ParamConfig['test_per_point'] == 0:
        # Get test loss and accuracy
        test_loss, test_acc, test_batches = model.validate_or_test(x_test, y_test)
        test_loss /= test_batches
        test_acc /= test_batches

        message('Test Loss:', test_loss),
        message('#Test accuracy:', test_acc)
    else:
        test_acc = None

    message('Number of accepted cases: {} of {} total'.format(
        total_accepted_cases, train_batches * model.train_batch_size))

    return validate_acc, test_acc


def validate_point_message2(model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater):
    # Get training loss
    train_loss = model.get_training_loss(x_train, y_train)

    # Get validation loss and accuracy
    validate_loss, validate_acc, validate_batches = model.validate_or_test(x_validate, y_validate)
    validate_loss /= validate_batches
    validate_acc /= validate_batches

    # Get test loss and accuracy
    # [NOTE]: In this version, test at each validate point is fixed.
    test_loss, test_acc, test_batches = model.validate_or_test(x_test, y_test)
    test_loss /= test_batches
    test_acc /= test_batches

    message("""\
Validate Point: Epoch {} Iteration {} Batch {} TotalBatch {}
Training Loss: {}
History Training Loss: {}
Validate Loss: {}
#Validate accuracy: {}
Test Loss: {}
#Test accuracy: {}
Number of accepted cases: {} of {} total""".format(
        updater.epoch, updater.iteration, updater.epoch_train_batches, updater.total_train_batches,
        train_loss,
        updater.epoch_history_train_loss / updater.epoch_train_batches,
        validate_loss,
        validate_acc,
        test_loss,
        test_acc,
        updater.total_accepted_cases, updater.total_seen_cases,
    ))

    if Config['temp_job'] == 'check_selected_data_label':
        message("""\
Epoch label count: {}
Total label count: {}""".format(
            updater.epoch_label_count,
            updater.total_label_count,
        ))

    return validate_acc, test_acc


def episode_final_message(best_validate_acc, best_iteration, test_score, start_time):
    message('$Final results:')
    message('$  best test accuracy:\t\t{} %'.format((test_score * 100.0) if test_score is not None else None))
    message('$  best validation accuracy: {}'.format(best_validate_acc))
    message('$  obtained at iteration {}'.format(best_iteration))
    message('$  Time passed: {:.2f}s'.format(time.time() - start_time))


def train_raw_MNIST():
    model = MNISTModel()

    # Load the dataset and config
    x_train, y_train, x_validate, y_validate, x_test, y_test, train_size, validate_size, test_size = pre_process_data()
    patience, patience_increase, improvement_threshold, validation_frequency = pre_process_config(model, train_size)

    updater = RawUpdater(model, [x_train, y_train])

    # Train the network
    # Some variables
    history_accuracy = []

    # To prevent the double validate point
    last_validate_point = -1

    best_validate_acc = -np.inf
    best_iteration = 0
    test_score = 0.0
    start_time = time.time()

    for epoch in range(ParamConfig['epoch_per_episode']):
        print('[Epoch {}]'.format(epoch))
        message('[Epoch {}]'.format(epoch))

        updater.start_new_epoch()
        epoch_start_time = time.time()

        kf = get_minibatches_idx(train_size, model.train_batch_size, shuffle=True)

        for _, train_index in kf:
            part_train_cost = updater.add_batch(train_index, updater, history_accuracy)

            if updater.total_train_batches > 0 and \
                    updater.total_train_batches != last_validate_point and \
                    updater.total_train_batches % validation_frequency == 0:
                last_validate_point = updater.total_train_batches
                validate_acc, test_acc = validate_point_message2(
                    model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater)
                history_accuracy.append(validate_acc)

                if validate_acc > best_validate_acc:
                    # improve patience if loss improvement is good enough
                    if (1. - validate_acc) < (1. - best_validate_acc) * improvement_threshold:
                        patience = max(patience, updater.iteration * patience_increase)
                    best_validate_acc = validate_acc
                    best_iteration = updater.iteration
                    test_score = test_acc

            if updater.total_train_batches >= patience:
                break

        message("Epoch {} of {} took {:.3f}s".format(
            epoch, ParamConfig['epoch_per_episode'], time.time() - epoch_start_time))
        if updater.iteration >= patience:
            break

    episode_final_message(best_validate_acc, best_iteration, test_score, start_time)


def train_SPL_MNIST():
    model = MNISTModel()

    # Load the dataset and config
    x_train, y_train, x_validate, y_validate, x_test, y_test, train_size, validate_size, test_size = pre_process_data()
    patience, patience_increase, improvement_threshold, validation_frequency = pre_process_config(model, train_size)

    updater = SPLUpdater(model, [x_train, y_train], ParamConfig['epoch_per_episode'])

    # Train the network
    # Some variables
    history_accuracy = []

    # To prevent the double validate point
    last_validate_point = -1

    best_validate_acc = -np.inf
    best_iteration = 0
    test_score = 0.0
    start_time = time.time()

    for epoch in range(ParamConfig['epoch_per_episode']):
        print('[Epoch {}]'.format(epoch))
        message('[Epoch {}]'.format(epoch))

        updater.start_new_epoch()
        epoch_start_time = time.time()

        kf = get_minibatches_idx(train_size, model.train_batch_size, shuffle=True)

        for _, train_index in kf:
            part_train_cost = updater.add_batch(train_index, updater, history_accuracy)

            if updater.total_train_batches > 0 and \
                    updater.total_train_batches != last_validate_point and \
                    updater.total_train_batches % validation_frequency == 0:
                last_validate_point = updater.total_train_batches

                validate_acc, test_acc = validate_point_message2(
                    model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater)
                history_accuracy.append(validate_acc)

                if validate_acc > best_validate_acc:
                    # improve patience if loss improvement is good enough
                    if (1. - validate_acc) < (1. - best_validate_acc) * improvement_threshold:
                        patience = max(patience, updater.iteration * patience_increase)
                    best_validate_acc = validate_acc
                    best_iteration = updater.iteration
                    test_score = test_acc

            if updater.total_train_batches >= patience:
                break

        message("Epoch {} of {} took {:.3f}s".format(
            epoch, ParamConfig['epoch_per_episode'], time.time() - epoch_start_time))
        if updater.iteration >= patience:
            break

    episode_final_message(best_validate_acc, best_iteration, test_score, start_time)


def train_policy_MNIST():
    model = MNISTModel()

    # Create the policy network
    input_size = MNISTModel.get_policy_input_size()
    print('Input size of policy network:', input_size)
    policy_model_name = eval(PolicyConfig['policy_model_name'])
    policy = policy_model_name(input_size=input_size)
    # policy = LRPolicyNetwork(input_size=input_size)
    policy.message_parameters()

    # Load the dataset and config
    x_train, y_train, x_validate, y_validate, x_test, y_test, train_size, validate_size, test_size = pre_process_data()
    patience, patience_increase, improvement_threshold, validation_frequency = pre_process_config(model, train_size)

    for episode in range(PolicyConfig['num_episodes']):
        print('[Episode {}]'.format(episode))
        message('[Episode {}]'.format(episode))

        model.reset_parameters()

        # Train the network
        # Some variables
        history_accuracy = []

        # To prevent the double validate point
        last_validate_point = -1

        # Speed reward
        first_over_cases = None

        # get small training data
        x_train_small, y_train_small = get_part_data(x_train, y_train, ParamConfig['train_small_size'])
        train_small_size = len(x_train_small)
        message('Training small size:', train_small_size)

        updater = TrainPolicyUpdater(model, [x_train_small, y_train_small], policy)

        best_validate_acc = -np.inf
        best_iteration = 0
        test_score = 0.0
        start_time = time.time()

        for epoch in range(ParamConfig['epoch_per_episode']):
            print('[Epoch {}]'.format(epoch))
            message('[Epoch {}]'.format(epoch))

            updater.start_new_epoch()
            epoch_start_time = time.time()

            kf = get_minibatches_idx(train_small_size, model.train_batch_size, shuffle=True)

            for _, train_index in kf:
                part_train_cost = updater.add_batch(train_index, updater, history_accuracy)

                if updater.total_train_batches > 0 and \
                        updater.total_train_batches != last_validate_point and \
                        updater.total_train_batches % validation_frequency == 0:
                    last_validate_point = updater.total_train_batches
                    validate_acc, test_acc = validate_point_message2(
                        model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater)
                    history_accuracy.append(validate_acc)

                    if validate_acc > best_validate_acc:
                        # improve patience if loss improvement is good enough
                        if (1. - validate_acc) < (1. - best_validate_acc) * improvement_threshold:
                            patience = max(patience, updater.iteration * patience_increase)
                        best_validate_acc = validate_acc
                        best_iteration = updater.iteration
                        test_score = test_acc

                    # Check speed rewards
                    if first_over_cases is None and validate_acc >= PolicyConfig['speed_reward_threshold']:
                        first_over_cases = updater.total_accepted_cases

                if updater.total_train_batches >= patience:
                    break

            message("Epoch {} of {} took {:.3f}s".format(
                epoch, ParamConfig['epoch_per_episode'], time.time() - epoch_start_time))

            # Immediate reward
            if PolicyConfig['immediate_reward']:
                validate_acc = model.get_test_acc(x_validate, y_validate)
                policy.reward_buffer.append(validate_acc)

            if updater.iteration >= patience:
                break

        episode_final_message(best_validate_acc, best_iteration, test_score, start_time)

        # Updating policy
        if PolicyConfig['speed_reward']:
            expected_total_cases = ParamConfig['epoch_per_episode'] * train_small_size
            if first_over_cases is None:
                first_over_cases = expected_total_cases
            terminal_reward = float(first_over_cases) / expected_total_cases
            policy.update(-np.log(terminal_reward))

            message('First over cases:', first_over_cases)
            message('Total cases:', expected_total_cases)
            message('Terminal reward:', terminal_reward)
        else:
            validate_acc = model.get_test_acc(x_validate, y_validate)
            policy.update(validate_acc)

        if Config['policy_save_freq'] > 0 and episode % Config['policy_save_freq'] == 0:
            policy.save_policy(PolicyConfig['policy_model_file'].replace('.npz', '_ep{}.npz'.format(episode)))
            policy.save_policy()


def train_actor_critic_MNIST():
    model = MNISTModel()

    # Create the policy network
    input_size = MNISTModel.get_policy_input_size()
    print('Input size of policy network:', input_size)
    policy_model_name = eval(PolicyConfig['policy_model_name'])
    actor = policy_model_name(input_size=input_size)
    # actor = LRPolicyNetwork(input_size=input_size)
    actor.message_parameters()
    critic = CriticNetwork(feature_size=input_size, batch_size=model.train_batch_size)

    # Load the dataset and config
    x_train, y_train, x_validate, y_validate, x_test, y_test, train_size, validate_size, test_size = pre_process_data()
    patience, patience_increase, improvement_threshold, validation_frequency = pre_process_config(model, train_size)

    # Train the network
    for episode in range(PolicyConfig['num_episodes']):
        print('[Episode {}]'.format(episode))
        message('[Episode {}]'.format(episode))

        model.reset_parameters()

        # Train the network
        # Some variables
        history_accuracy = []

        # To prevent the double validate / AC update point
        last_validate_point = -1
        last_AC_update_point = -1

        # get small training data
        x_train_small, y_train_small = get_part_data(x_train, y_train, ParamConfig['train_small_size'])
        train_small_size = len(x_train_small)
        message('Training small size:', train_small_size)

        updater = ACUpdater(model, [x_train_small, y_train_small], actor)

        best_validate_acc = -np.inf
        best_iteration = 0
        test_score = 0.0
        start_time = time.time()

        for epoch in range(ParamConfig['epoch_per_episode']):
            print('[Epoch {}]'.format(epoch))
            message('[Epoch {}]'.format(epoch))

            total_accepted_cases = 0
            history_train_loss = 0
            train_batches = 0
            epoch_start_time = time.time()

            kf = get_minibatches_idx(train_small_size, model.train_batch_size, shuffle=True)

            actor.start_new_epoch()

            for _, train_index in kf:
                part_train_cost = updater.add_batch(train_index, updater, history_accuracy)

                if updater.total_train_batches > 0 and \
                        updater.total_train_batches != last_AC_update_point and \
                        updater.total_train_batches % PolicyConfig['AC_update_freq'] == 0:
                    last_AC_update_point = updater.total_train_batches

                    # [NOTE]: The batch is the batch sent into updater, NOT the buffer's batch.
                    inputs = x_train_small[train_index]
                    targets = y_train_small[train_index]
                    probability = updater.last_probability
                    actions = updater.last_action

                    # Get immediate reward
                    # [NOTE]: Cost gap reward is removed
                    # if PolicyConfig['cost_gap_AC_reward']:
                    #     cost_old = part_train_cost
                    #
                    #     cost_new = model.f_cost_without_decay(inputs, targets)
                    #     imm_reward = cost_old - cost_new
                    valid_part_x, valid_part_y = get_part_data(
                        np.asarray(x_validate), np.asarray(y_validate), PolicyConfig['immediate_reward_sample_size'])
                    _, valid_acc, validate_batches = model.validate_or_test(valid_part_x, valid_part_y)
                    imm_reward = valid_acc / validate_batches

                    # Get new state, new actions, and compute new Q value
                    probability_new = model.get_policy_input(inputs, targets, updater, history_accuracy)
                    actions_new = actor.take_action(probability_new, log_replay=False)

                    Q_value_new = critic.Q_function(state=probability_new, action=actions_new)
                    if epoch < ParamConfig['epoch_per_episode'] - 1:
                        label = PolicyConfig['actor_gamma'] * Q_value_new + imm_reward
                    else:
                        label = imm_reward

                    # Update the critic Q network
                    Q_loss = critic.update(probability, actions, floatX(label))

                    # Update actor network
                    actor_loss = actor.update_raw(probability, actions,
                                                  np.full(actions.shape, label, dtype=probability.dtype))

                    if PolicyConfig['AC_update_freq'] >= ParamConfig['display_freq'] or \
                       updater.total_train_batches % ParamConfig['display_freq'] == 0:
                        message('Epoch {}\tTotalBatches {}\tCost {}\tCritic loss {}\tActor loss {}'
                                .format(epoch, updater.total_train_batches, part_train_cost, Q_loss, actor_loss))

                if updater.total_train_batches > 0 and \
                        updater.total_train_batches != last_validate_point and \
                        updater.total_train_batches % validation_frequency == 0:
                    last_validate_point = updater.total_train_batches

                    validate_acc, test_acc = validate_point_message2(
                        model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater)
                    history_accuracy.append(validate_acc)

                    if validate_acc > best_validate_acc:
                        # improve patience if loss improvement is good enough
                        if (1. - validate_acc) < (1. - best_validate_acc) * improvement_threshold:
                            patience = max(patience, updater.iteration * patience_increase)
                        best_validate_acc = validate_acc
                        best_iteration = updater.iteration
                        test_score = test_acc

                if updater.total_train_batches >= patience:
                    break

            message("Epoch {} of {} took {:.3f}s".format(
                epoch, ParamConfig['epoch_per_episode'], time.time() - epoch_start_time))
            if updater.total_train_batches >= patience:
                break

        episode_final_message(best_validate_acc, best_iteration, test_score, start_time)

        # [NOTE]: Remove update of terminal reward in AC.
        # validate_acc = model.get_test_acc(x_validate, y_validate)
        # actor.update(validate_acc)

        if Config['policy_save_freq'] > 0 and episode % Config['policy_save_freq'] == 0:
            actor.save_policy(PolicyConfig['policy_model_file'].replace('.npz', '_ep{}.npz'.format(episode)))
            actor.save_policy()


def test_policy_MNIST():
    if Config['train_type'] == 'deterministic':
        raise NotImplementedError('Deterministic test policy is not implemented in MNIST')

    model = MNISTModel()

    input_size = MNISTModel.get_policy_input_size()
    print('Input size of policy network:', input_size)

    # Load the dataset and config
    x_train, y_train, x_validate, y_validate, x_test, y_test, train_size, validate_size, test_size = pre_process_data()
    patience, patience_increase, improvement_threshold, validation_frequency = pre_process_config(model, train_size)

    if Config['train_type'] == 'random_drop':
        updater = RandomDropUpdater(model, [x_train, y_train], ParamConfig['random_drop_number_file'])
    else:
        # Build policy
        policy_model_name = eval(PolicyConfig['policy_model_name'])
        policy = policy_model_name(input_size=input_size)
        # policy = LRPolicyNetwork(input_size=input_size)
        policy.load_policy()
        policy.message_parameters()
        updater = TestPolicyUpdater(model, [x_train, y_train], policy)

    # Train the network
    # Some variables
    history_accuracy = []

    # To prevent the double validate point
    last_validate_point = -1

    best_validate_acc = -np.inf
    best_iteration = 0
    test_score = 0.0
    start_time = time.time()

    for epoch in range(ParamConfig['epoch_per_episode']):
        print('[Epoch {}]'.format(epoch))
        message('[Epoch {}]'.format(epoch))

        updater.start_new_epoch()
        epoch_start_time = time.time()

        kf = get_minibatches_idx(train_size, model.train_batch_size, shuffle=True)

        for _, train_index in kf:
            part_train_cost = updater.add_batch(train_index, updater, history_accuracy)

            if updater.total_train_batches > 0 and \
                    updater.total_train_batches != last_validate_point and \
                    updater.total_train_batches % validation_frequency == 0:
                last_validate_point = updater.total_train_batches
                validate_acc, test_acc = validate_point_message2(
                    model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater)
                history_accuracy.append(validate_acc)

                if validate_acc > best_validate_acc:
                    # improve patience if loss improvement is good enough
                    if (1. - validate_acc) < (1. - best_validate_acc) * improvement_threshold:
                        patience = max(patience, updater.iteration * patience_increase)
                    best_validate_acc = validate_acc
                    best_iteration = updater.iteration
                    test_score = test_acc

            if updater.total_train_batches >= patience:
                break

        message("Epoch {} of {} took {:.3f}s".format(
            epoch, ParamConfig['epoch_per_episode'], time.time() - epoch_start_time))
        if updater.iteration >= patience:
            break

    episode_final_message(best_validate_acc, best_iteration, test_score, start_time)


def main(args=None):
    process_before_train(args, ParamConfig)

    try:
        if Config['train_type'] == 'raw':
            train_raw_MNIST()
        elif Config['train_type'] == 'self_paced':
            train_SPL_MNIST()
        elif Config['train_type'] == 'policy':
            train_policy_MNIST()
        elif Config['train_type'] == 'actor_critic':
            train_actor_critic_MNIST()
        elif Config['train_type'] == 'deterministic':
            test_policy_MNIST()
        elif Config['train_type'] == 'stochastic':
            test_policy_MNIST()
        elif Config['train_type'] == 'random_drop':
            test_policy_MNIST()
        else:
            raise Exception('Unknown train type {}'.format(Config['train_type']))
    except:
        message(traceback.format_exc())
    finally:
        finalize_logging_file()


if __name__ == '__main__':
    main()
