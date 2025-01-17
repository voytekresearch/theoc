#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""Oscillatory coding, as LNP."""
import sys
import cloudpickle
import pandas as pd
import os
import numpy as np
from scipy.signal import welch

from fakespikes import neurons, rates
from pacpy.pac import ozkurt as pacfn

from itertools import product
from collections import defaultdict

from theoc.lfp import create_lfps
from theoc.metrics import discrete_dist
from theoc.metrics import discrete_entropy
from theoc.metrics import discrete_mutual_information
from theoc.metrics import normalize

EPS = np.finfo(float).eps


def save_result(name, result):
    if not name.endswith(".pkl"):
        name += ".pkl"
    with open(name, "wb") as f:
        cloudpickle.dump(result, f)


def load_result(name):
    if not name.endswith(".pkl"):
        name += ".pkl"
    with open(name, "rb") as f:
        result = cloudpickle.load(f)
    return result


def phi(x, m=1, b=0):
    """The rectified-linear transform"""
    x = x - b
    x[x <= 0] = 0
    x = x * m
    return x


def oscillatory_coupling(num_pop=50,
                         num_background=5,
                         t=5,
                         osc_rate=6,
                         f=6,
                         g=1,
                         g_max=1,
                         q=0.5,
                         stim_rate=12,
                         frac_std=.01,
                         m=8,
                         priv_std=0,
                         dt=0.001,
                         squelch=False,
                         save=None,
                         stim_seed=None,
                         seed=None):
    """Run a single OC simulation."""

    # -- Safety -------------------------------------------------------------
    if g > g_max:
        raise ValueError("g must be < g_max")
    min_rate = 2
    if stim_rate <= min_rate:
        raise ValueError(f"stim_rate must be greater {min_rate}")
    if f < 3:
        raise ValueError("f (freq) must be greater then 2")

    # q can't be exactly 0
    q += EPS

    # -- Init ---------------------------------------------------------------
    # Poisson neurons
    backspikes = neurons.Spikes(num_background, t, dt=dt, seed=seed)
    ocspikes = neurons.Spikes(num_pop,
                              t,
                              dt=dt,
                              private_stdev=priv_std,
                              seed=seed)
    times = ocspikes.times  # brevity

    # Set stim std. It must be relative to stim_rate
    stim_std = frac_std * stim_rate

    # -- Drives -------------------------------------------------------------
    # Create biases/drives
    d_bias = {}

    # Background is 2 Hz
    d_bias['back'] = rates.constant(times, 2)

    # Drives proper:
    # 1. O
    d_bias['osc'] = rates.osc(times, osc_rate, f)
    if squelch:
        d_bias['osc'] = rates.constant(times, osc_rate)

    # 2. S
    d_bias['stim'] = rates.stim(times,
                                stim_rate,
                                stim_std,
                                seed=stim_seed,
                                min_rate=min_rate)

    # -
    # Linear modulatons
    d_bias['mult'] = d_bias['stim'] * ((g_max - g + 1) * d_bias['osc'])
    d_bias['add'] = d_bias['stim'] + (g * d_bias['osc'])
    d_bias['sub'] = d_bias['stim'] - (g * d_bias['osc'])
    div = d_bias['stim'] / (g * d_bias['osc'])
    sub = d_bias['stim'] - (g * d_bias['osc'])
    d_bias['div_sub'] = (q * div) + ((1 - q) * sub)

    # -
    # Nonlinear transform (RELU)
    for k, v in d_bias.items():
        d_bias[k] = phi(v)

    # -- Simulate spiking ---------------------------------------------------
    # Create a ref stimulus
    stim_ref = d_bias["stim"]

    # Create the background pool.
    b_spks = backspikes.poisson(d_bias['back'])

    # Create OC outputs. This includes a null op stimulus, our baseline.
    d_spikes = {}
    for k in d_bias.keys():
        d_spikes[k + "_p"] = np.hstack([ocspikes.poisson(d_bias[k]), b_spks])

    # -- I ------------------------------------------------------------------
    # Scale stim
    y_ref = normalize(stim_ref)
    d_rescaled = {}
    d_rescaled["stim_ref"] = y_ref
    if not squelch:
        d_rescaled["osc_ref"] = normalize(d_bias["osc"])
    else:
        # Can't norm a single number
        d_rescaled["osc_ref"] = np.zeros_like(d_bias["osc"])

    # Calc MI and H
    d_mis = {}
    d_deltas = {}
    d_hs = {}
    d_py = {}

    # Save ref H and dist
    d_py["stim_ref"] = discrete_dist(y_ref, m)
    d_hs["stim_ref"] = discrete_entropy(y_ref, m)

    # p(y), H, MI following rate norm
    for k in d_spikes.keys():
        y = normalize(d_spikes[k].sum(1))
        d_rescaled[k] = y
        d_py[k] = discrete_dist(y, m)
        d_mis[k] = discrete_mutual_information(y_ref, y, m)
        d_hs[k] = discrete_entropy(y, m)

    # Change in MI
    for k in d_mis.keys():
        d_deltas[k] = d_mis[k] - d_mis["stim_p"]

    # -- LFP ----------------------------------------------------------------
    d_lfps = {}
    for k in d_spikes.keys():
        d_lfps[k] = create_lfps(d_spikes[k], tau=0.002, dt=.001)

    # -- Extract peak power -------------------------------------------------
    d_powers = {}
    d_centers = {}
    for k in d_lfps.keys():
        freq, spectrum = welch(d_lfps[k],
                               fs=1000,
                               scaling='spectrum',
                               average='median')
        max_i = np.argmax(spectrum)
        d_powers[k] = spectrum[max_i]
        d_centers[k] = freq[max_i]

    # -- Measure OC using PAC -----------------------------------------------
    low_f = (int(f - 2), int(f + 2))
    high_f = (80, 250)

    d_pacs = {}
    for k in d_lfps.keys():
        d_pacs[k] = pacfn(d_lfps['osc_p'], d_lfps[k], low_f, high_f)

    # -
    result = {
        'MI': d_mis,
        'dMI': d_deltas,
        'H': d_hs,
        'PAC': d_pacs,
        'power': d_powers,
        'center': d_centers,
        'p_y': d_py,
        'bias': d_bias,
        'spikes': d_spikes,
        'rescaled': d_rescaled,
        'lfp': d_lfps,
        'times': times
    }

    if save is not None:
        save_result(save, result)

    return result