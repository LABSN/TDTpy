'''
.. module:: tdt.dsp_buffer
    :synopsis: Module for handling I/O with the buffers on the DSP devices
.. moduleauthor:: Brad Buran <bburan@alum.mit.edu
'''
import time
import numpy as np

from .util import dtype_to_type_str, resolution
from .dsp_error import DSPError
from .constants import RCX_BUFFER
from .abstract_ring_buffer import AbstractRingBuffer

import logging
log = logging.getLogger(__name__)


class DSPBuffer(AbstractRingBuffer):
    '''
    Given the circuit object and tag name, return a buffer object that serves
    as a wrapper around a SerStore or SerSource component.  See the TDTPy
    documentation for more detail on buffers.
    '''

    # List of all attributes available.  The majority of these attributes are
    # generated by inspection of the RCX file and some may be useful for the
    # user (e.g. fs, size, etc.).

    ATTRIBUTES = [
        'data_tag', 'idx_tag', 'size_tag', 'sf_tag', 'cycle_tag',
        'dec_tag', 'src_type', 'dest_type', 'compression', 'resolution',
        'sf', 'dec_factor', 'fs', 'n_slots', 'n_samples', 'size',
        'n_slots_max', 'n_samples_max', 'size_max', 'channels',
        'block_size']

    def __init__(self, circuit, data_tag, idx_tag=None, size_tag=None,
                 sf_tag=None, cycle_tag=None, dec_tag=None, block_size=1,
                 src_type='float32', dest_type='float32', channels=1,
                 dec_factor=None):

        if data_tag not in circuit.tags:
            raise ValueError("%s: Does not have data tag %s"
                             % (circuit, data_tag))
        elif not circuit.tags[data_tag][1] == RCX_BUFFER:
            raise ValueError("Tag %s is not a buffer tag" % data_tag)

        self.circuit = circuit
        self._iface = circuit._iface
        self._zbus = circuit._zbus
        self.data_tag = data_tag
        self.channels = channels
        self.block_size = int(block_size)

        self.size_tag = self.find_tag(size_tag, '_n', True, 'size')
        self.idx_tag = self.find_tag(idx_tag, '_i', True, 'index')
        self.sf_tag = self.find_tag(sf_tag, '_sf', False, 'scaling factor')
        self.cycle_tag = self.find_tag(cycle_tag, '_c', False, 'cycles')
        self.dec_tag = self.find_tag(dec_tag, '_d', False, 'decimation')
        self.sf = self.get_tag(self.sf_tag, 1, 'scaling factor')

        if dec_factor is not None:
            if self.dec_tag is not None:
                self.circuit.set_tag(self.dec_tag, dec_factor)
            elif dec_factor != 1:
                m = 'Decimation tag for %s must be available to set ' \
                    'decimation factor to %d' % (self.data_tag, dec_factor)
                raise ValueError(m)

        self.dec_factor = self.get_tag(self.dec_tag, 1, 'decimation factor')
        self.fs = circuit.fs / float(self.dec_factor)
        log.debug('%s: Sampling rate %f', self, self.fs)

        # Numpy's dtype function is quite powerful and accepts a variety of
        # strings as well as other dtype objects and returns the right answer.
        self.src_type = np.dtype(src_type)
        self.dest_type = np.dtype(dest_type)

        # Number of samples compressed into a single slot.  The RPvds works
        # with 32 bit words.  If we are compressing our data, calculate the
        # number of samples that are compressed into a single 32 bit word.
        # If src_type is int8, we know we are compressing 4 samples into a
        # single 32 bit (4 byte) word.
        self.compression = int(4/np.nbytes[self.src_type])

        # Query buffer for it's size in terms of slots, samples and samples per
        # channel
        self._update_size()

        # Convert our preferred representation for the data type to TDT's
        # preferred representation for the data type.
        self.vex_src_type = dtype_to_type_str(self.src_type)
        self.vex_dest_type = dtype_to_type_str(self.dest_type)

        try:
            self.resolution = resolution(self.src_type, self.sf)
        except:
            # Does the logic change if sf is not 1?  We should never see this
            # use-case but let's add a check for safety.
            if self.sf != 1:
                raise ValueError("FIXME")
            self.resolution = np.finfo(self.src_type).resolution

        # The number of slots in the buffer must be a multiple of channel
        # number, otherwise data will be lost.  This is a requirement of the
        # RPvds circuit, so let's check to make sure this requirement is met as
        # it is a very common mistake to make.
        if (self.n_slots % self.channels) != 0:
            mesg = 'Buffer size must be a multiple of the channel number'
            raise DSPError(self, mesg)

        # Spit out debugging information
        log.debug('Initialized %s', self._get_debug_info())

    def find_tag(self, tag, default_prefix, required, name):
        '''
        Locates tag that tracks a feature of the buffer

        Parameters
        ----------
        tag : {None, str}
            Name provided by the end-user code
        default_prefix : str
            Prefix to append to the data tag name to create the default tag
            name for the feature.
        required : bool
            If the tag is required and it is missing, raise an error.
            Otherwise, return None.
        name : str
            What the tag represents. Used by the logging and exception
            machinery to create a useful message.

        Returns
        -------
        tag_name : {None, str}
            Name of tag. If no tag found and it is not required, return None.

        Raises
        ------
        ValueError
            If tag cannot be found and it is required.
        '''
        # If no name was provided create a default one.
        if tag is None:
            tag = self.data_tag + default_prefix

        # If tag exists, return it.
        if tag in self.circuit.tags:
            log.debug("%s: found %s tag %s", self, name, tag)
            return tag

        # If we have reached this point, the tag is missing. If it was
        # required, raise an error.
        if required:
            m = '%s tag for %s must be present in circuit' % (name, self)
            raise ValueError(m)
        log.debug('%s: no tag found for %s', self, name)

    def get_tag(self, tag, default, name):
        '''
        Returns value of tag that tracks a feature of the buffer

        Parameters
        ----------
        tag : {None, str}
            Name provided by the end-user code
        default : {int, float}
            Default value of feature if tag is missing.
        name : str
            What the tag represents. Used by the logging and exception
            machinery to create a useful message.

        Returns
        -------
        value : {int, float}
            Value of tag. If no tag is present, default is returned.
        '''
        if tag is None:
            log.debug('%s: %s is %r (default)', self, name, default)
            return default
        value = self.circuit.get_tag(tag)
        log.debug('%s: %s is %r', self, name, value)
        return value

    def _get_debug_info(self):
        attr_strings = ['{0}: {1}'.format(*a)
                        for a in self.attributes().items()]
        return '%s: %s' % (self, ', '.join(attr_strings))

    def attributes(self, attributes=None):
        if attributes is None:
            attributes = self.ATTRIBUTES
        return dict((attr, getattr(self, attr)) for attr in attributes)

    def __getstate__(self):
        '''
        Provides support for pickling, which is required by the multiprocessing
        module for launching a new process.  _iface is a PyIDispatch object,
        which does not support pickling, so we just delete them and pickle the
        rest.
        '''
        state = self.__dict__.copy()
        del state['_iface']
        return state

    def __setstate__(self, state):
        '''
        Loads the state and reconnects the COM objects
        '''
        self.__dict__.update(state)
        self._iface = self.circuit._iface

    def _read(self, offset, length):
        raise NotImplementedError

    def _write(self, offset, data):
        raise NotImplementedError

    def set_size(self, size):
        if not self._iface.SetTagVal(self.size_tag, size):
            raise DSPError(self, "Unable to set buffer size to %d" % size)
        self._update_size()

    def _update_size(self):
        '''
        Query current state of buffer (size and current index).  If data
        compression is being used, multiple samples can fit into a single slot
        of a RPvds buffer.  We want the index and size attributes to accurately
        reflect the number of samples per channel in the buffer, not the number
        of slots.

        For example, assume I am storing 16 channels in a buffer with two
        samples compressed into each slot.  After the DSP clock has counted 10
        samples, 10 samples per channel will have been stored for a total of
        160 samples.  However, only 80 slots will have been filled.

        n_slots
            number of slots in buffer
        n_samples
            number of samples in buffer
        size
            number of samples per channel
        '''
        # update size
        self.n_slots_max = self._iface.GetTagSize(self.data_tag)
        if self.size_tag is not None:
            self.n_slots = self.circuit.get_tag(self.size_tag)
        else:
            self.n_slots = self.n_slots_max
            log.debug("%s: no size tag available, using GetTagSize", self)

        self.n_samples = round(self.n_slots * self.compression)
        self.n_samples_max = round(self.n_slots_max * self.compression)
        self.size = round(self.n_samples / self.channels)
        self.size_max = round(self.n_samples_max / self.channels)
        self.sample_time = self.size / self.fs
        self.max_sample_time = self.size_max / self.fs

    def _get_empty_array(self, samples):
        return np.empty((self.channels, samples), dtype=self.dest_type)

    def __str__(self):
        return "{0}:{1}".format(self.circuit, self.data_tag)

    def __repr__(self):
        return "<{0}:{1}:{2}:{3}>".format(self.circuit, self.data_tag,
                                          self.write_index, self.size)

    def clear(self):
        '''
        Set buffer to zero

        Due to a bug in the TDT ActiveX library, RPco.X.ZeroTag does not work
        on certain hardware configurations.  TDT (per conversation with Chris
        Walters and Nafi Yasar) have indicated that they will not fix this bug.
        They have also indicated that they may deprecate ZeroTag in future
        versions of the ActiveX library.

        As a workaround, this method zeros out the buffer by writing a stream
        of zeros.
        '''
        zeros = np.zeros(self.n_samples)
        self._iface.WriteTagV(self.data_tag, 0, zeros)

    def _acquire(self, trigger, end_condition, samples=None, trials=1,
                 intertrial_interval=0, poll_interval=0.1, reset_read=True):
        '''
        Convenience function to handle core logic of acquisition.  Use
        `DSPBuffer.acquire` or `DSPBuffer.acquire_samples` instead.
        '''
        acquired_data = []
        for i in range(trials):
            if reset_read:
                self.reset_read(0)
            samples_acquired = 0
            time.sleep(intertrial_interval)
            trial_data = []
            self.circuit.trigger(trigger)
            while True:
                if end_condition(self, samples_acquired):
                    break
                new_data = self.read()
                samples_acquired += new_data.shape[-1]
                trial_data.append(new_data)
                log.debug('%s: acquired %d samples', self, samples_acquired)
                time.sleep(poll_interval)
            remaining_data = self.read()
            samples_acquired += remaining_data.shape[-1]
            trial_data.append(remaining_data)
            trial_data = np.hstack(trial_data)
            if samples is not None:
                trial_data = trial_data[:, :samples]
            acquired_data.append(trial_data[np.newaxis])
        return np.vstack(acquired_data)

    def acquire(self, trigger, handshake_tag, end_condition=None, trials=1,
                intertrial_interval=0, poll_interval=0.1, reset_read=True):
        '''
        Fire trigger and acquire resulting block of data

        Data will be continuously spooled while the status of the handshake_tag
        is being monitored, so a single acquisition block can be larger than
        the size of the buffer; however, be sure to set poll_interval to a
        duration that is sufficient to to download data before it is
        overwritten.

        Parameters
        ----------
        trigger
            Trigger that starts data acquistion (can be A, B, or 1-9)
        handshake_tag
            Tag indicating status of data acquisition
        end_condition
            If None, any change to the value of handshake_tag after trigger is
            fired indicates data acquisition is complete.  Otherwise, data
            acquisition is done when the value of handshake_tag equals the
            end_condition.  end_condition may be a Python callable that takes
            the value of the handshake tag and returns a boolean indicating
            whether acquisition is complete or not.
        trials
            Number of trials to collect
        intertrial_interval
            Time to pause in between trials
        poll_interval
            Time to pause in between polling hardware
        reset_read
            Should the read index be reset at the beginning of each acquisition
            sweep?  If data is written starting at the first index of the
            buffer, then this should be True.  If data is written continuously
            to the buffer with no reset of the index in between sweeps, then
            this should be False.

        Returns
        -------
        acquired_trials : ndarray
            A 3-dimensional array in the format (trial, channel, sample).

        Examples
        --------
        >>> buffer.acquire(1, 'sweep_done')
        >>> buffer.acquire(1, 'sweep_done', True)
        '''
        # TODO: should we set the read index to = write index?

        if end_condition is None:
            handshake_value = self.circuit.get_tag(handshake_tag)

            def is_done(x):
                return x != handshake_value
        elif not callable(end_condition):
            def is_done(x):
                return x == end_condition
        else:
            is_done = end_condition

        def wrapper(dsp_buffer, samples):
            current_value = dsp_buffer.circuit.get_tag(handshake_tag)
            return is_done(current_value)

        return self._acquire(
            trigger, end_condition=wrapper, samples=None,
            trials=trials, intertrial_interval=intertrial_interval,
            poll_interval=poll_interval, reset_read=reset_read)

    def acquire_samples(self, trigger, samples, trials=1,
                        intertrial_interval=0, poll_interval=0.1,
                        reset_read=True):
        '''
        Fire trigger and acquire n samples
        '''
        if samples % self.block_size:
            raise ValueError("Number of samples must be a multiple of "
                             "block size")
        log.debug('%s: attempting to acquire %d samples', self, samples)

        def is_done(b, s):
            return s >= samples
        return self._acquire(
            trigger, end_condition=is_done, samples=samples,
            trials=trials, intertrial_interval=intertrial_interval,
            poll_interval=poll_interval, reset_read=reset_read)


class ReadableDSPBuffer(DSPBuffer):

    def _get_write_index(self):
        index = int(self.circuit.get_tag(self.idx_tag))
        actual_index = index * self.compression / self.channels
        log.debug("%s: index raw %d, actual %d", self, index, actual_index)
        return actual_index

    write_index = property(_get_write_index)

    def _get_write_cycle(self):
        if self.cycle_tag is None:
            return None
        cycle = int(self.circuit.get_tag(self.cycle_tag))
        log.debug("%s: cycle", cycle)
        return cycle

    write_cycle = property(_get_write_cycle)

    def _read(self, offset, length):
        log.debug("%s: read offset %d, read size %d", self, offset, length)
        if length == 0:
            data = np.array([], dtype=self.dest_type)
            return data.reshape((self.channels, -1))

        # At this point, we have already done the necessary computation of
        # offset and read size so all we have to do is pass those values
        # directly to the ReadTagVEX function.
        data = self._iface.ReadTagVEX(
            self.data_tag, offset, length,
            self.vex_src_type, self.vex_dest_type, self.channels)
        return np.divide(data, self.sf).astype(self.dest_type)


class WriteableDSPBuffer(DSPBuffer):

    def _get_read_index(self):
        # This returns the current sample that's been read
        index = int(self.circuit.get_tag(self.idx_tag))
        return index * self.compression / self.channels

    read_index = property(_get_read_index)

    def _get_read_cycle(self):
        if self.cycle_tag is None:
            return None
        cycle = self.circuit.get_tag(self.cycle_tag)
        log.debug("%s: cycle", cycle)
        return cycle

    read_cycle = property(_get_read_cycle)

    def _write(self, offset, data):
        log.debug("%s: write %d samples at %d", self, len(data), offset)
        return self._iface.WriteTagV(self.data_tag, offset, data)

    def set(self, data):
        '''
        Assumes data is written starting at the first index of the buffer. Use
        for epoch-based playout.
        '''
        data = np.asarray(data)
        size = data.shape[-1]
        if size > self.size_max:
            mesg = "Cannot write %d samples to buffer" % size
            raise DSPError(self, mesg)
        if self.size_tag is not None:
            self.set_size(size)
        elif size != self.size:
            mesg = "Buffer size cannot be configured"
            raise DSPError(self, mesg)

        if size == 0:
            return

        if self.vex_src_type != 'F32':
            raise NotImplementedError
        if not self._iface.WriteTagV(self.data_tag, 0, data):
            raise DSPError(self, "write failed")
        log.debug("%s: set buffer with %d samples", self, size)
        self.total_samples_written += size
