import sys
import re
import binascii
import struct
from argparse_addons import Integer
from matplotlib import pyplot as plt

from .. import database

#TODO: implement --show-* arguments
#TODO: use timestamps if existing
#TODO: allow output of decode as input
#TODO: optionally write result to output file
#TODO: customizable line formats


# Matches 'candump' output, i.e. "vcan0  1F0   [8]  00 00 00 00 00 00 1B C1".
RE_CANDUMP = re.compile(r'^\s*(?:\(.*?\))?\s*\S+\s+([0-9A-F]+)\s*\[\d+\]\s*([0-9A-F ]*)$')
# Matches 'candump -l' (or -L) output, i.e. "(1594172461.968006) vcan0 1F0#0000000000001BC1"
RE_CANDUMP_LOG = re.compile(r'^\(\d+\.\d+\)\s+\S+\s+([\dA-F]+)#([\dA-F]*)$')


def _mo_unpack(mo):
    frame_id = mo.group(1)
    frame_id = '0' * (8 - len(frame_id)) + frame_id
    frame_id = binascii.unhexlify(frame_id)
    frame_id = struct.unpack('>I', frame_id)[0]
    data = mo.group(2)
    data = data.replace(' ', '')
    data = binascii.unhexlify(data)

    return frame_id, data


def _do_decode(args):
    dbase = database.load_file(args.database,
                               encoding=args.encoding,
                               frame_id_mask=args.frame_id_mask,
                               strict=not args.no_strict)
    re_format = None

    plotter = Plotter(dbase, args)

    line_number = 0
    while True:
        line = sys.stdin.readline()
        line_number += 1

        # Break at EOF.
        if not line:
            break

        line = line.strip('\r\n')

        # Auto-detect on first valid line.
        if re_format is None:
            mo = RE_CANDUMP.match(line)

            if mo:
                re_format = RE_CANDUMP
            else:
                mo = RE_CANDUMP_LOG.match(line)

                if mo:
                    re_format = RE_CANDUMP_LOG
        else:
            mo = re_format.match(line)

        if mo:
            frame_id, data = _mo_unpack(mo)
            plotter.add_msg(line_number, frame_id, data)
        else:
            plotter.failed_to_parse_line(line_number)
            print("failed to parse line: %r" % line)

    plotter.plot()


class Plotter:

    def __init__(self, dbase, args):
        self.dbase = dbase
        self.decode_choices = not args.no_decode_choices
        self.show_invalid_syntax = args.show_invalid_syntax
        self.show_unknown_frames = args.show_unknown_frames
        self.show_invalid_data = args.show_invalid_data
        self.signals = Signals(args.signals)

        self.x_invalid_syntax = []
        self.x_unknown_frames = []
        self.x_invalid_data = []

    def add_msg(self, timestamp, frame_id, data):
        try:
            message = self.dbase.get_message_by_frame_id(frame_id)
        except KeyError:
            if self.show_unknown_frames:
                self.x_unknown_frames.append(timestamp)
            print('Unknown frame id {0} (0x{0:x})'.format(frame_id))
            return

        try:
            decoded_signals = message.decode(data, self.decode_choices)
        except Exception as e:
            if self.show_invalid_data:
                self.x_invalid_data.append(timestamp)
            print('Failed to parse data of frame id {0} (0x{0:x}): {1}'.format(frame_id, e))
            return

        for signal in decoded_signals:
            x = timestamp
            y = decoded_signals[signal]
            signal = message.name + '.' + signal
            self.signals.add_value(signal, x, y)

    def failed_to_parse_line(self, timestamp):
        if self.show_invalid_syntax:
            self.x_invalid_syntax.append(timestamp)

    def plot(self):
        self.signals.plot()
        plt.figlegend()
        plt.show()

class Signals:

    SEP_SG = re.escape('.')

    WILDCARD_MANY = re.escape('*')
    WILDCARD_ONE  = re.escape('?')

    def __init__(self, signals):
        self.args = signals
        self.signals = []
        self.values = {}

        if signals:
            for sg in signals:
                self.add_signal(sg)
        else:
            self.add_signal('*')

    def add_signal(self, signal):
        signal = re.escape(signal)
        if self.SEP_SG not in signal:
            signal = self.WILDCARD_MANY + self.SEP_SG + signal
        signal = signal.replace(self.WILDCARD_MANY, '.*')
        signal = signal.replace(self.WILDCARD_ONE, '.')
        signal += '$'
        reo = re.compile(signal)
        self.signals.append(reo)

    def add_value(self, signal, x, y):
        if not self.is_displayed_signal(signal):
            return

        if signal not in self.values:
            graph = Graph()
            self.values[signal] = graph
        else:
            graph = self.values[signal]
        graph.x.append(x)
        graph.y.append(y)

    def is_displayed_signal(self, signal):
        for reo in self.signals:
            if reo.match(signal):
                return True
        return False

    def plot(self):
        for sg in self.values:
            x = self.values[sg].x
            y = self.values[sg].y
            plt.plot(x, y, label=sg)

class Graph:

    __slots__ = ('x', 'y')

    def __init__(self):
        self.x = []
        self.y = []


def add_subparser(subparsers):
    decode_parser = subparsers.add_parser(
        'plot',
        description=('Decode "candump" CAN frames or the output of cantools decode '
                     'read from standard input and plot them using matplotlib.'))
    decode_parser.add_argument(
        '-c', '--no-decode-choices',
        action='store_true',
        help='Do not convert scaled values to choice strings.')
    decode_parser.add_argument(
        '-e', '--encoding',
        help='File encoding of dbc file.')
    decode_parser.add_argument(
        '--no-strict',
        action='store_true',
        help='Skip database consistency checks.')
    decode_parser.add_argument(
        '-m', '--frame-id-mask',
        type=Integer(0),
        help=('Only compare selected frame id bits to find the message in the '
              'database. By default the candump and database frame ids must '
              'be equal for a match.'))
    decode_parser.add_argument(
        '--show-invalid-syntax',
        action='store_true',
        help='Show a marker for lines which could not be parsed.')
    decode_parser.add_argument(
        '--show-unknown-frames',
        action='store_true',
        help='Show a marker for messages which are not contained in the database file.')
    decode_parser.add_argument(
        '--show-invalid-data',
        action='store_true',
        help='Show a marker for messages with data which could not be parsed.')
    decode_parser.add_argument(
        'database',
        help='Database file.')
    decode_parser.add_argument(
        'signals',
        nargs='*',
        help='The signals to be plotted.')
    decode_parser.set_defaults(func=_do_decode)
