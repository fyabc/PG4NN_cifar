#! /usr/bin/python

from __future__ import print_function, unicode_literals

from batch_updater import *
from config import CifarConfig as ParamConfig
from critic_network import CriticNetwork
from model_CIFAR10 import CIFARModelBase, CIFARModel
from policy_network import PolicyNetworkBase
from reward_checker import RewardChecker, get_reward_checker
from utils import *
from utils_CIFAR10 import load_cifar10_data, split_cifar10_data, pre_process_CIFAR10_data, \
    prepare_CIFAR10_data

__author__ = 'fyabc'


# [NOTE]: In CIFAR10, validate point at end of each epoch.
def epoch_message(model, x_train, y_train, x_validate, y_validate, x_test, y_test,
                  updater, history_train_loss,
                  epoch, start_time, train_batches, total_accepted_cases):
    # Get training loss
    train_loss = model.get_training_loss(x_train, y_train)

    # Get validation loss and accuracy
    validate_loss, validate_acc, validate_batches = model.validate_or_test(x_validate, y_validate)
    validate_loss /= validate_batches
    validate_acc /= validate_batches
    updater.history_accuracy.append(validate_acc)

    # Get test loss and accuracy
    test_loss, test_acc, test_batches = model.validate_or_test(x_test, y_test)
    test_loss /= test_batches
    test_acc /= test_batches

    message("Epoch {} of {} took {:.3f}s".format(epoch, ParamConfig['epoch_per_episode'], time.time() - start_time))
    message('Training Loss:', train_loss)
    message('History Training Loss:', history_train_loss / train_batches)
    message('Validate Loss:', validate_loss)
    message('#Validate accuracy:', validate_acc)
    message('Test Loss:', test_loss),
    message('#Test accuracy:', test_acc)
    message('Number of accepted cases: {} of {} total'.format(total_accepted_cases, x_train.shape[0]))


def train_raw_CIFAR10():
    # Create neural network model
    model = CIFARModelBase.get_by_name(ParamConfig['model_name'])()
    # model = VaniliaCNNModel()

    # Load the dataset
    x_train, y_train, x_validate, y_validate, x_test, y_test, \
        train_size, validate_size, test_size = pre_process_CIFAR10_data()

    updater = RawUpdater(model, [x_train, y_train], prepare_data=prepare_CIFAR10_data)

    if ParamConfig['warm_start']:
        model.load_model(Config['model_file'])

    # Train the network
    # Some variables

    # Learning rate discount
    lr_discount_41, lr_discount_61 = False, False

    # To prevent the double validate point
    last_validate_point = -1

    best_validate_acc = -np.inf
    best_iteration = 0
    test_score = 0.0
    start_time = time.time()

    for epoch in range(ParamConfig['epoch_per_episode']):
        epoch_start_time = start_new_epoch(updater, epoch)

        kf = get_minibatches_idx(train_size, model.train_batch_size, shuffle=True)

        for _, train_index in kf:
            part_train_cost = updater.add_batch(train_index)

            if updater.total_train_batches > 0 and \
                    updater.total_train_batches != last_validate_point and \
                    updater.total_train_batches % ParamConfig['valid_freq'] == 0:
                last_validate_point = updater.total_train_batches
                validate_acc, test_acc = validate_point_message(
                    model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater,
                    # validate_size=validate_size,  # Use part validation set in baseline
                    run_test=True,
                )

                if validate_acc > best_validate_acc:
                    best_validate_acc = validate_acc
                    best_iteration = updater.iteration
                    test_score = test_acc

            if isinstance(model, CIFARModel):
                if not lr_discount_41 and updater.total_accepted_cases >= 41 * train_size:
                        lr_discount_41 = True
                        model.update_learning_rate()
                if not lr_discount_61 and updater.total_accepted_cases > 61 * train_size:
                        lr_discount_61 = True
                        model.update_learning_rate()

        message("Epoch {} of {} took {:.3f}s".format(
            epoch, ParamConfig['epoch_per_episode'], time.time() - epoch_start_time))

    episode_final_message(best_validate_acc, best_iteration, test_score, start_time)

    if ParamConfig['save_model']:
        model.save_model()


def train_SPL_CIFAR10():
    # Create neural network model
    model = CIFARModelBase.get_by_name(ParamConfig['model_name'])()
    # model = VaniliaCNNModel()

    # Load the dataset
    x_train, y_train, x_validate, y_validate, x_test, y_test, \
        train_size, validate_size, test_size = pre_process_CIFAR10_data()

    updater = SPLUpdater(model, [x_train, y_train], ParamConfig['epoch_per_episode'], prepare_data=prepare_CIFAR10_data)

    if ParamConfig['warm_start']:
        model.load_model(Config['model_file'])

    # Train the network
    # Some variables

    best_validate_acc = -np.inf
    best_iteration = 0
    test_score = 0.0
    start_time = time.time()

    for epoch in range(ParamConfig['epoch_per_episode']):
        epoch_start_time = start_new_epoch(updater, epoch)

        kf = get_minibatches_idx(train_size, model.train_batch_size, shuffle=True)

        for _, train_index in kf:
            part_train_cost = updater.add_batch(train_index)

        validate_acc, test_acc = validate_point_message(
            model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater)

        if validate_acc > best_validate_acc:
            best_validate_acc = validate_acc
            best_iteration = updater.iteration
            test_score = test_acc

        if isinstance(model, CIFARModel):
            if (epoch + 1) in (41, 61):
                model.update_learning_rate()

        message("Epoch {} of {} took {:.3f}s".format(
            epoch, ParamConfig['epoch_per_episode'], time.time() - epoch_start_time))

    episode_final_message(best_validate_acc, best_iteration, test_score, start_time)


def train_policy_CIFAR10():
    # Create neural network model
    model = CIFARModelBase.get_by_name(ParamConfig['model_name'])()
    # model = VaniliaCNNModel()

    # Create the policy network
    input_size = CIFARModelBase.get_policy_input_size()
    message('Input size of policy network:', input_size)
    policy = PolicyNetworkBase.get_by_name(PolicyConfig['policy_model_type'])(input_size=input_size)
    # policy = LRPolicyNetwork(input_size=input_size)

    policy.check_load()

    # Load the dataset
    x_train, y_train, x_validate, y_validate, x_test, y_test, \
        train_size, validate_size, test_size = pre_process_CIFAR10_data()

    reward_checker_type = RewardChecker.get_by_name(PolicyConfig['reward_checker'])

    # Train the network
    start_episode = 1 + PolicyConfig['start_episode']
    for episode in range(start_episode, start_episode + PolicyConfig['num_episodes']):
        start_new_episode(model, policy, episode)
        model.reset_learning_rate()

        # Train the network
        # Some variables

        # Learning rate discount
        lr_discount_41, lr_discount_61 = False, False

        # To prevent the double validate point
        last_validate_point = -1

        # get small training data
        # x_train_small, y_train_small = get_part_data(x_train, y_train, ParamConfig['train_small_size'])
        # [WARNING] Do NOT shuffle here!!!
        x_train_small, y_train_small = x_train, y_train
        train_small_size = len(x_train_small)
        message('Training small size:', train_small_size)

        # Speed reward
        reward_checker = get_reward_checker(
            reward_checker_type,
            ParamConfig['epoch_per_episode'] * train_small_size
        )

        updater = TrainPolicyUpdater(model, [x_train_small, y_train_small], policy, prepare_data=prepare_CIFAR10_data)

        best_validate_acc = -np.inf
        best_iteration = 0
        test_score = 0.0
        start_time = time.time()

        for epoch in range(ParamConfig['epoch_per_episode']):
            epoch_start_time = start_new_epoch(updater, epoch)

            kf = get_minibatches_idx(train_small_size, model.train_batch_size, shuffle=True)

            for _, train_index in kf:
                part_train_cost = updater.add_batch(train_index)

                if updater.total_train_batches > 0 and \
                        updater.total_train_batches != last_validate_point and \
                        updater.total_train_batches % ParamConfig['valid_freq'] == 0:
                    last_validate_point = updater.total_train_batches
                    validate_acc, test_acc = validate_point_message(
                        model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater, reward_checker,
                        run_test=False,
                    )

                    if validate_acc > best_validate_acc:
                        best_validate_acc = validate_acc
                        best_iteration = updater.iteration
                        test_score = test_acc

            if isinstance(model, CIFARModel):
                if not lr_discount_41 and updater.total_accepted_cases >= 41 * train_size:
                        lr_discount_41 = True
                        model.update_learning_rate()
                if not lr_discount_61 and updater.total_accepted_cases > 61 * train_size:
                        lr_discount_61 = True
                        model.update_learning_rate()

            message("Epoch {} of {} took {:.3f}s".format(
                epoch, ParamConfig['epoch_per_episode'], time.time() - epoch_start_time))

        episode_final_message(best_validate_acc, best_iteration, test_score, start_time)

        policy.update(reward_checker)

        if PolicyConfig['policy_save_freq'] > 0 and episode % PolicyConfig['policy_save_freq'] == 0:
            policy.save_policy(PolicyConfig['policy_save_file'], episode)


def train_actor_critic_CIFAR10():
    # Create neural network model
    model = CIFARModelBase.get_by_name(ParamConfig['model_name'])()
    # model = VaniliaCNNModel()

    # Create the actor network
    input_size = CIFARModelBase.get_policy_input_size()
    print('Input size of actor network:', input_size)
    actor = PolicyNetworkBase.get_by_name(PolicyConfig['policy_model_type'])(input_size=input_size)
    # actor = LRPolicyNetwork(input_size=input_size)
    critic = CriticNetwork(feature_size=input_size, batch_size=model.train_batch_size)

    actor.check_load()

    # Load the dataset
    x_train, y_train, x_validate, y_validate, x_test, y_test = split_cifar10_data(load_cifar10_data())

    message('Validation data size:', y_validate.shape[0])
    message('Test data size:', y_test.shape[0])

    # Train the network
    start_episode = 1 + PolicyConfig['start_episode']
    for episode in range(start_episode, start_episode + PolicyConfig['num_episodes']):
        print('[Episode {}]'.format(episode))
        message('[Episode {}]'.format(episode))

        actor.message_parameters()

        if ParamConfig['warm_start']:
            model.load_model(Config['model_file'])
        else:
            model.reset_parameters()
        model.reset_learning_rate()

        # To prevent the double validate / AC update point
        # last_validate_point = -1
        last_AC_update_point = -1

        # get small training data
        # x_train_small, y_train_small = get_part_data(x_train, y_train, ParamConfig['train_small_size'])
        # [WARNING] Do NOT shuffle here!!!
        x_train_small, y_train_small = x_train, y_train
        train_small_size = len(x_train_small)
        message('Training small size:', train_small_size)

        updater = ACUpdater(model, [x_train_small, y_train_small], actor, prepare_data=prepare_CIFAR10_data)

        for epoch in range(ParamConfig['epoch_per_episode']):
            epoch_start_time = start_new_epoch(updater, epoch)

            kf = get_minibatches_idx(train_small_size, model.train_batch_size, shuffle=True)

            for _, train_index in kf:
                part_train_cost = updater.add_batch(train_index)

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
                    probability_new = model.get_policy_input(inputs, targets, updater, updater.history_accuracy)
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

            if isinstance(model, CIFARModel):
                if (epoch + 1) in (41, 61):
                    model.update_learning_rate()

            message("Epoch {} of {} took {:.3f}s".format(
                epoch, ParamConfig['epoch_per_episode'], time.time() - epoch_start_time))

            validate_acc, test_acc = validate_point_message(
                model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater)

        model.test(x_test, y_test)

        # [NOTE]: Remove update of terminal reward in AC.
        # validate_loss, validate_acc, validate_batches = model.validate_or_test(x_validate, y_validate)
        # validate_acc /= validate_batches
        # actor.update(validate_acc)

        if PolicyConfig['policy_save_freq'] > 0 and episode % PolicyConfig['policy_save_freq'] == 0:
            actor.save_policy(PolicyConfig['policy_save_file'], episode)


def test_policy_CIFAR10():
    # Create neural network model
    model = CIFARModelBase.get_by_name(ParamConfig['model_name'])()
    # model = VaniliaCNNModel()

    input_size = CIFARModelBase.get_policy_input_size()
    message('Input size of policy network:', input_size)

    # Load the dataset and get small training data
    x_train, y_train, x_validate, y_validate, x_test, y_test = split_cifar10_data(load_cifar10_data())

    message('Training data size:', y_train.shape[0])
    message('Validation data size:', y_validate.shape[0])
    message('Test data size:', y_test.shape[0])

    if ParamConfig['warm_start']:
        model.load_model()

    if Config['train_type'] == 'random_drop':
        updater = RandomDropUpdater(model, [x_train, y_train],
                                    PolicyConfig['random_drop_number_file'], prepare_data=prepare_CIFAR10_data,
                                    drop_num_type='vp', valid_freq=ParamConfig['valid_freq'])
    else:
        # Build policy
        policy = PolicyNetworkBase.get_by_name(PolicyConfig['policy_model_type'])(input_size=input_size)
        # policy = LRPolicyNetwork(input_size=input_size)
        policy.load_policy()
        policy.message_parameters()
        updater = TestPolicyUpdater(model, [x_train, y_train], policy, prepare_data=prepare_CIFAR10_data)

    # Train the network
    # Some variables
    best_validate_acc = -np.inf
    best_iteration = 0
    test_score = 0.0
    start_time = time.time()

    for epoch in range(ParamConfig['epoch_per_episode']):
        epoch_start_time = start_new_epoch(updater, epoch)

        kf = get_minibatches_idx(updater.data_size, model.train_batch_size, shuffle=True)

        for _, train_index in kf:
            part_train_cost = updater.add_batch(train_index)

        validate_acc, test_acc = validate_point_message(
            model, x_train, y_train, x_validate, y_validate, x_test, y_test, updater,
            run_test=True,
        )

        if validate_acc > best_validate_acc:
            best_validate_acc = validate_acc
            best_iteration = updater.iteration
            test_score = test_acc

        if isinstance(model, CIFARModel):
            if (epoch + 1) in (41, 61):
                model.update_learning_rate()

        message("Epoch {} of {} took {:.3f}s".format(
            epoch, ParamConfig['epoch_per_episode'], time.time() - epoch_start_time))

    episode_final_message(best_validate_acc, best_iteration, test_score, start_time)

    model.test(x_test, y_test)


def new_train_CIFAR10():
    pass
        
        
def main():
    dataset_main({
        'raw': train_raw_CIFAR10,
        'self_paced': train_SPL_CIFAR10,
        'spl': train_SPL_CIFAR10,

        'policy': train_policy_CIFAR10,
        'reinforce': train_policy_CIFAR10,
        'speed': train_policy_CIFAR10,

        'actor_critic': train_actor_critic_CIFAR10,
        'ac': train_actor_critic_CIFAR10,

        # 'test': test_policy_CIFAR10,
        'deterministic': test_policy_CIFAR10,
        'stochastic': test_policy_CIFAR10,
        'random_drop': test_policy_CIFAR10,

        'new_train': new_train_CIFAR10,
    })


if __name__ == '__main__':
    main()
