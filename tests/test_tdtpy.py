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
def ai1(circuit):
    return circuit.get_buffer('ai1', 'r')


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
    time.sleep(0.1)

    n_dec = int(n / dec_factor)

    read_samples_dec = ai_dec.read()[0, :n_dec]
    write_samples_dec = write_samples[::dec_factor][:n_dec]
    np.testing.assert_allclose(write_samples_dec, read_samples_dec)


def test_circuit_incremential_write_read(project, ao1, ai1):
    n = round(ao1.fs)
    write = []
    read = []

    for i in range(10):
        write.append(np.random.uniform(size=n))

    ao1.write(write[0])
    project.trigger('A', 'high')
    for s in write[1:]:
        time.sleep(0.5)
        ao1.write(s)
        read.append(ai1.read())
    time.sleep(11*0.5)
    read.append(ai1.read())

    write = np.concatenate(write, axis=-1)
    read = np.concatenate(read, axis=-1)[0]
    # Be sure to correct for 2 sample delay
    np.testing.assert_allclose(write, read[:len(write)])


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
