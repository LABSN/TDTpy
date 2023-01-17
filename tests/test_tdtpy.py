import pytest
import time

import numpy as np

from tdt import DSPProject


BASE_FS = 97656.25


@pytest.fixture
def project():
    return DSPProject()


@pytest.fixture
def circuit(project):
    circuit = project.load_circuit('RZ6-debugging.rcx', 'RZ6', 1, latch_trigger=1)
    circuit.start()
    yield circuit
    circuit.stop()


@pytest.fixture
def ao1(circuit):
    return circuit.get_buffer('ao1', 'w')


@pytest.fixture
def ao2(circuit):
    return circuit.get_buffer('ao2', 'w')


@pytest.fixture
def ai1(circuit):
    return circuit.get_buffer('ai1', 'r')


@pytest.fixture
def ai2(circuit):
    return circuit.get_buffer('ai2', 'r')


def test_circuit_load(circuit):
    circuit.start()
    circuit.stop()


def test_buffer_fs(ao1, ai1):
    assert ao1.fs == BASE_FS
    assert ai1.fs == BASE_FS


def test_circuit_write_read(project, ao1, ai1):
    n = round(ao1.fs)
    write_samples = np.random.uniform(size=n)
    ao1.write(write_samples)
    project.trigger('A', 'high')
    time.sleep(1)

    # There is a two-sample delay in the circuit
    read_samples = ai1.read()[0, :n]
    np.testing.assert_allclose(write_samples, read_samples)


def test_buffer_detect_dec_factor(circuit):
    # The default decimation factor is 8 by default
    ai_dec1 = circuit.get_buffer('ai_dec1', 'r')
    assert ai_dec1.fs == (BASE_FS / 8)


@pytest.mark.parametrize("dec_factor", [1, 2, 4, 8])
def test_circuit_write_read_dec(project, circuit, ao1, dec_factor):
    ai_dec = circuit.get_buffer('ai_dec1', 'r', dec_factor=dec_factor)
    assert ai_dec.fs == (BASE_FS / dec_factor)

    n = round(ao1.fs / 10)
    t = np.arange(n) / ao1.fs
    write_samples = np.sin(2 * np.pi * 50 * t)
    ao1.write(write_samples)

    project.trigger('A', 'high')
    read_samples_dec = []
    for i in range(10):
        time.sleep(0.05)
        read_samples_dec.append(ai_dec.read())

    n_dec = int(n / dec_factor)
    read_samples_dec = np.concatenate(read_samples_dec, axis=-1)[0, :n_dec]
    write_samples_dec = write_samples[::dec_factor][:n_dec]
    np.testing.assert_allclose(write_samples_dec, read_samples_dec)


def test_circuit_write_too_slow(project, ao1):
    # This tests the condition where a subsequent write takes so long that the
    # samples generated by the output buffer run into an area of the ring
    # buffer that has not received new data yet.
    n = round(ao1.fs)
    ao1.write(np.random.uniform(size=n))
    project.trigger('A', 'high')
    time.sleep(1)
    with pytest.raises(IOError, match='Write was too slow and old samples were regenerated'):
        ao1.write(np.random.uniform(size=n))


def test_circuit_missing_initial_write(project, ao1):
    # This tests the condition where the first write to the output buffer
    # occurs after the circuit is started. This means that the buffer is not
    # properly initialized and is generating random samples (whatever existed
    # when the buffer memory was allocated)
    n = round(ao1.fs)
    project.trigger('A', 'high')
    with pytest.raises(IOError, match='Write was too slow and old samples were regenerated'):
        ao1.write(np.random.uniform(size=n))


def test_circuit_read_too_slow(project, ai1):
    n = round(ai1.fs)
    ai1.set_size(n)
    project.trigger('A', 'high')
    time.sleep(1)
    with pytest.raises(IOError, match='Read was too slow and unread samples were overwritten'):
        ai1.read()


def test_circuit_read_wrap(project, ai1, ai2):
    project.trigger('A', 'high')
    d1 = []
    d2 = []
    for i in range(15):
        time.sleep(0.1)
        d1.append(ai1.read())
        d2.append(ai2.read())
    project.trigger('A', 'low')
    d1.append(ai1.read())
    d2.append(ai2.read())
    d1 = np.concatenate(d1, axis=1)
    d2 = np.concatenate(d2, axis=1)
    assert d1.shape[-1] == ((ai1.read_cycle * ai1.n_slots) + ai1.read_index)
    assert d2.shape[-1] == ((ai2.read_cycle * ai2.n_slots) + ai2.read_index)
    assert d1.shape == d2.shape
    assert ai1.read_cycle != 0


@pytest.mark.parametrize("dec_factor", [1, 2, 4, 8])
def test_circuit_dec_read_wrap(project, circuit, dec_factor):
    # Verify that decimated buffer reads properly wrap around
    ai1 = circuit.get_buffer('ai_dec1', 'r', dec_factor=dec_factor)
    read_time = ai1.n_samples / ai1.fs
    print(read_time)
    project.trigger('A', 'high')
    d1 = []
    for i in range(15):
        time.sleep(read_time * 0.1)
        d1.append(ai1.read())
    project.trigger('A', 'low')
    d1.append(ai1.read())
    d1 = np.concatenate(d1, axis=1)
    assert d1.shape[-1] == ((ai1.read_cycle * ai1.n_slots) + ai1.read_index)
    assert ai1.read_cycle != 0


def test_circuit_write_wrap(project, ao1, ao2, ai1, ai2):
    d1 = np.random.uniform(size=ao1.available())
    ao1.write(d1)
    w1 = [d1]

    d2 = np.random.uniform(size=ao2.available())
    ao2.write(d2)
    w2 = [d2]
    r1 = []
    r2 = []

    project.trigger('A', 'high')
    for i in range(15):
        time.sleep(0.1)
        d1 = np.random.uniform(size=ao1.available())
        ao1.write(d1)
        w1.append(d1)
        d2 = np.random.uniform(size=ao2.available())
        ao2.write(d2)
        w2.append(d2)

        r1.append(ai1.read())
        r2.append(ai2.read())

    project.trigger('A', 'low')
    d1 = np.random.uniform(size=ao1.available())
    ao1.write(d1)
    w1.append(d1)
    d2 = np.random.uniform(size=ao2.available())
    ao2.write(d2)
    w2.append(d2)
    r1.append(ai1.read())
    r2.append(ai2.read())

    w1 = np.concatenate(w1, axis=-1)
    w2 = np.concatenate(w2, axis=-1)
    r1 = np.concatenate(r1, axis=-1)[0]
    r2 = np.concatenate(r2, axis=-1)[0]

    assert r1.shape == r2.shape
    n = r1.shape[0]

    np.testing.assert_array_almost_equal(w1[:n], r1)
    np.testing.assert_array_almost_equal(w2[:n], r2)
