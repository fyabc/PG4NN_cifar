# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import sys
import os

ProjectRootPath = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ProjectRootPath)

import matplotlib.pyplot as plt

from config import LogPath

__author__ = 'fyabc'


Interval = 3


def get_test_acc_list(filename, dataset='mnist', interval=Interval):
    abs_filename = os.path.join(LogPath, dataset, filename)

    with open(abs_filename, 'r') as f:
        result = [
            float(line.split()[-1])
            for line in f
            if line.startswith('Test accuracy:')
        ]

    result = [e for i, e in enumerate(result) if i % interval == 0]

    return result


def plot():
    raw = get_test_acc_list('log-mnist-raw-Flip1.txt')
    best80 = get_test_acc_list('log-mnist-raw-FlipBest80.txt')
    spl = get_test_acc_list('log-mnist-spl-ForceFlip1.txt')

    m0r0b2 = get_test_acc_list('log-mnist-stochastic-lr-m0r0b2.txt')
    m2r_2b2 = get_test_acc_list('log-mnist-stochastic-lr-ForceFlip1.txt')
    m_2r2b2 = get_test_acc_list('log-mnist-stochastic-lr-m_2r2b2.txt')
    m_3r3b2 = get_test_acc_list('log-mnist-stochastic-lr-m_3r3b2.txt')

    speed = get_test_acc_list('log-mnist-stochastic-lr-Flip2.txt')

    plt.plot(raw, label='raw')
    plt.plot(best80, label='best 80%')
    plt.plot(spl, label='spl')

    plt.plot(speed, label='speed')

    plt.plot(m0r0b2, '--', label='m0r0b2')
    plt.plot(m2r_2b2, '--', label='m2r-2b2')
    plt.plot(m_2r2b2, '--', label='m-2r2b2')
    plt.plot(m_3r3b2, '--', label='m-3r3b2')

    plt.ylim(ymin=0.86, ymax=0.96)
    plt.xlim(xmax=1500 // Interval)

    plt.legend(loc='lower right')

    plt.show()


if __name__ == '__main__':
    plot()
