import numpy as np

from scipy.special import gamma, psi
from scipy import ndimage
from scipy.linalg import det
from scipy.stats import norm
from numpy import pi

from sklearn.neighbors import NearestNeighbors

EPS = np.finfo(float).eps


def change_direction(x):
    """Indictates whether a time series changes direction."""
    if x.ndim != 1:
        raise ValueError("x must be 1d")

    return np.sign(np.diff(x))


def Z(p):
    """The Z function - norm.ppf(p)"""
    return norm.ppf(p)


def signal_discriminations(x_true, x):
    """Find hits, misses, ..., for every point by comparing the series."""
    d_true = change_direction(x_true)
    d = change_direction(x)

    # Hits: sign is not zero in ref, and x agrees
    m = np.nonzero(d_true)
    hits = (d_true[m] == d[m])

    # Misses: sign is not zero in ref, and s disagrees
    misses = np.logical_not(hits)

    # False alarm: sign is zero in ref, and x agrees
    m = np.logical_not(m)
    false_alarms = (d_true[m] == d[m])

    # Corrent reject: sign is zero in ref, and x agrees
    correct_rejects = np.logical_not(false_alarms)

    # Convert all the bools to ints
    hits = hits.astype(int)
    misses - misses.astype(int)
    false_alarms = false_alarms.astype(int)
    correct_rejects - correct_rejects.astype(int)

    return hits, misses, false_alarms, correct_rejects


def d_prime(x_true, x):
    """Estimate d' between momentary changes"""

    # ---------------------------------------------------------
    # NOTE: this code was modified from:
    # https://lindeloev.net/calculating-d-in-python-and-php/
    # ---------------------------------------------------------

    # These are time-series, but we want averages for the whole series
    hits, misses, false_alarms, correct_rejects = signal_discriminations(
        x_true, x)

    hit = np.mean(hits)  # bound 0-1
    miss = np.mean(misses)
    fa = np.mean(false_alarms)
    cr = np.mean(correct_rejects)

    # Floors an ceilings are
    # replaced by half hits and half FA's
    half_hit = 0.5 / (hit + miss)
    half_fa = 0.5 / (fa + cr)

    # Calculate hit_rate and avoid d' infinity
    hit_rate = hit / (hit + misses)
    if hit_rate == 1:
        hit_rate = 1 - half_hit
    if hit_rate == 0:
        hit_rate = half_hit

    # Calculate false alarm rate and avoid d' infinity
    fa_rate = fa / (fa + cr)
    if fa_rate == 1:
        fa_rate = 1 - half_fa
    if fa_rate == 0:
        fa_rate = half_fa

    d_prime = Z(hit_rate) - Z(fa_rate)

    return d_prime


def normalize(x):
    x = (x.astype(np.float) - np.nanmin(x)) / (np.nanmax(x) - np.nanmin(x))
    return x


def l2_error(y_ref, y):
    """Returns the least squared error.
    
    Parameters
    ==========

    y_ref : array-like, shape (n_samples)
        The reference data
    y : array-like, shape (n_samples)
        The test data
    """
    delta = y - y_ref
    return np.sum(delta**2)


def discrete_dist(x, m):
    '''Returns a discrete distribution on x, of size m.

    Parameters
    ===========

    x : array-like, shape (n_samples)
        The data the entropy of which is computed

    m : int, optional
        Number of symbols possible
    '''
    counts = np.histogram(x[np.isfinite(x)], bins=m)[0]
    dist = counts / counts.sum()

    return dist


def discrete_entropy(x, m, logfn=np.log10, normalize=True):
    '''Returns the entropy of the X.

    Parameters
    ===========

    x : array-like, shape (n_samples)
        The data the entropy of which is computed

    m : int, optional
        Number of symbols possible

    logfn: function
        A numpy log function
    '''
    dist = discrete_dist(x, m)
    dist = dist[np.nonzero(dist)[0]]  # drop zeros
    h = -np.sum(dist * logfn(dist))

    if normalize:
        h /= logfn(m)

    return h


def discrete_mutual_information(x, y, m, logfn=np.log10, normalize=False):
    '''Returns the entropy of the X.

    Parameters
    ===========

    x : array-like, shape (n_samples)
        The first data the MI of which is computed

    y : array-like, shape (n_samples)
        The second data the MI of which is computed

    m : int, optional
        Number of symbols possible
    
    logfn: function
        A numpy log function

    normalize: bool, optional
        Should we normalize the MI?
    '''

    # Entropies
    h_x = discrete_entropy(x, m, logfn=logfn)
    h_y = discrete_entropy(y, m, logfn=logfn)
    h_xy = discrete_entropy(np.concatenate([x, y]), m, logfn=logfn)

    # Mutual Information
    mi_xy = (h_x + h_y) - h_xy

    if normalize:
        return mi_xy / np.sqrt(h_x * h_y)
    else:
        return mi_xy


def nearest_distances(X, k=1):
    '''
    X = array(N,M)
    N = number of points
    M = number of dimensions

    returns the distance to the kth nearest neighbor for every point in X
    '''
    knn = NearestNeighbors(n_neighbors=k + 1)
    knn.fit(X)
    d, _ = knn.kneighbors(X)  # the first nearest neighbor is itself
    return d[:, -1]  # returns the distance to the kth nearest neighbor


def entropy_gaussian(C):
    '''
    Entropy of a gaussian variable with covariance matrix C
    '''
    if np.isscalar(C):  # C is the variance
        return .5 * (1 + np.log(2 * pi)) + .5 * np.log(C)
    else:
        n = C.shape[0]  # dimension
        return .5 * n * (1 + np.log(2 * pi)) + .5 * np.log(abs(det(C)))


def continuous_entropy(X, k=1):
    ''' Returns the entropy of the X.

    **********************************************************
    Code copied from:
    https://gist.github.com/GaelVaroquaux/ead9898bd3c973c40429
    **********************************************************

    These computations rely on nearest-neighbor statistics

    Parameters
    ===========

    X : array-like, shape (n_samples, n_features)
        The data the entropy of which is computed

    k : int, optional
        number of nearest neighbors for density estimation

    Notes
    ======

    Kozachenko, L. F. & Leonenko, N. N. 1987 Sample estimate of entropy
    of a random vector. Probl. Inf. Transm. 23, 95-101.
    See also: Evans, D. 2008 A computationally efficient estimator for
    mutual information, Proc. R. Soc. A 464 (2093), 1203-1215.
    and:
    Kraskov A, Stogbauer H, Grassberger P. (2004). Estimating mutual
    information. Phys Rev E 69(6 Pt 2):066138.
    '''

    # Distance to kth nearest neighbor
    r = nearest_distances(X, k)  # squared distances
    n, d = X.shape
    volume_unit_ball = (pi**(.5 * d)) / gamma(.5 * d + 1)
    '''
    F. Perez-Cruz, (2008). Estimation of Information Theoretic Measures
    for Continuous Random Variables. Advances in Neural Information
    Processing Systems 21 (NIPS). Vancouver (Canada), December.

    return d*mean(log(r))+log(volume_unit_ball)+log(n-1)-log(k)
    '''
    return (d * np.mean(np.log(r + np.finfo(X.dtype).eps)) +
            np.log(volume_unit_ball) + psi(n) - psi(k))


def continuous_mutual_information(variables, k=1):
    '''
    **********************************************************
    Code copied from:
    https://gist.github.com/GaelVaroquaux/ead9898bd3c973c40429
    **********************************************************

    These computations rely on nearest-neighbor statistics

    Returns the mutual information between any number of variables.
    Each variable is a matrix X = array(n_samples, n_features)
    where
      n = number of samples
      dx,dy = number of dimensions

    Optionally, the following keyword argument can be specified:
      k = number of nearest neighbors for density estimation

    Example: mutual_information((X, Y)), mutual_information((X, Y, Z), k=5)
    '''
    if len(variables) < 2:
        raise AttributeError(
            "Mutual information must involve at least 2 variables")
    all_vars = np.hstack(variables)
    return (sum([entropy(X, k=k) for X in variables]) - entropy(all_vars, k=k))


def continuous_mutual_information_2d(x, y, sigma=1, normalized=False):
    """
    **********************************************************
    Code copied from:
    https://gist.github.com/GaelVaroquaux/ead9898bd3c973c40429
    **********************************************************

    These computations rely on nearest-neighbor statistics

    Computes (normalized) mutual information between two 1D variate from a
    joint histogram.

    Parameters
    ----------
    x : 1D array
        first variable

    y : 1D array
        second variable

    sigma: float
        sigma for Gaussian smoothing of the joint histogram

    Returns
    -------
    nmi: float
        the computed similariy measure

    """
    bins = (256, 256)

    jh = np.histogram2d(x, y, bins=bins)[0]

    # smooth the jh with a gaussian filter of given sigma
    ndimage.gaussian_filter(jh, sigma=sigma, mode='constant', output=jh)

    # compute marginal histograms
    jh = jh + EPS
    sh = np.sum(jh)
    jh = jh / sh
    s1 = np.sum(jh, axis=0).reshape((-1, jh.shape[0]))
    s2 = np.sum(jh, axis=1).reshape((jh.shape[1], -1))

    # Normalised Mutual Information of:
    # Studholme,  jhill & jhawkes (1998).
    # "A normalized entropy measure of 3-D medical image alignment".
    # in Proc. Medical Imaging 1998, vol. 3338, San Diego, CA, pp. 132-143.
    if normalized:
        mi = ((np.sum(s1 * np.log(s1)) + np.sum(s2 * np.log(s2))) /
              np.sum(jh * np.log(jh))) - 1
    else:
        mi = (np.sum(jh * np.log(jh)) - np.sum(s1 * np.log(s1)) -
              np.sum(s2 * np.log(s2)))

    return mi


###############################################################################
# Tests


def test_entropy():
    # Testing against correlated Gaussian variables
    # (analytical results are known)
    # Entropy of a 3-dimensional gaussian variable
    rng = np.random.RandomState(0)
    n = 50000
    d = 3
    P = np.array([[1, 0, 0], [0, 1, .5], [0, 0, 1]])
    C = np.dot(P, P.T)
    Y = rng.randn(d, n)
    X = np.dot(P, Y)
    H_th = entropy_gaussian(C)
    H_est = continuous_entropy(X.T, k=5)
    # Our estimated entropy should always be less that the actual one
    # (entropy estimation undershoots) but not too much
    np.testing.assert_array_less(H_est, H_th)
    np.testing.assert_array_less(.9 * H_th, H_est)


def test_mutual_information():
    # Mutual information between two correlated gaussian variables
    # Entropy of a 2-dimensional gaussian variable
    n = 50000
    rng = np.random.RandomState(0)
    #P = np.random.randn(2, 2)
    P = np.array([[1, 0], [0.5, 1]])
    C = np.dot(P, P.T)
    U = rng.randn(2, n)
    Z = np.dot(P, U).T
    X = Z[:, 0]
    X = X.reshape(len(X), 1)
    Y = Z[:, 1]
    Y = Y.reshape(len(Y), 1)
    # in bits
    MI_est = continuous_mutual_information((X, Y), k=5)
    MI_th = (entropy_gaussian(C[0, 0]) + entropy_gaussian(C[1, 1]) -
             entropy_gaussian(C))
    # Our estimator should undershoot once again: it will undershoot more
    # for the 2D estimation that for the 1D estimation
    print((MI_est, MI_th))
    np.testing.assert_array_less(MI_est, MI_th)
    np.testing.assert_array_less(MI_th, MI_est + .3)


def test_degenerate():
    # Test that our estimators are well-behaved with regards to
    # degenerate solutions
    rng = np.random.RandomState(0)
    x = rng.randn(50000)
    X = np.c_[x, x]
    assert np.isfinite(continuous_entropy(X))
    assert np.isfinite(
        continuous_mutual_information((x[:, np.newaxis], x[:, np.newaxis])))
    assert 2.9 < continuous_mutual_information_2d(x, x) < 3.1


def test_mutual_information_2d():
    # Mutual information between two correlated gaussian variables
    # Entropy of a 2-dimensional gaussian variable
    n = 50000
    rng = np.random.RandomState(0)
    #P = np.random.randn(2, 2)
    P = np.array([[1, 0], [.9, .1]])
    C = np.dot(P, P.T)
    U = rng.randn(2, n)
    Z = np.dot(P, U).T
    X = Z[:, 0]
    X = X.reshape(len(X), 1)
    Y = Z[:, 1]
    Y = Y.reshape(len(Y), 1)
    # in bits
    MI_est = continuous_mutual_information_2d(X.ravel(), Y.ravel())
    MI_th = (entropy_gaussian(C[0, 0]) + entropy_gaussian(C[1, 1]) -
             entropy_gaussian(C))
    print((MI_est, MI_th))
    # Our estimator should undershoot once again: it will undershoot more
    # for the 2D estimation that for the 1D estimation
    np.testing.assert_array_less(MI_est, MI_th)
    np.testing.assert_array_less(MI_th, MI_est + .2)


if __name__ == '__main__':
    # Run our tests
    test_entropy()
    test_mutual_information()
    test_degenerate()
    test_mutual_information_2d()