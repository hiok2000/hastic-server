from models import Model, AnalyticUnitCache

import scipy.signal
from scipy.fftpack import fft
from scipy.signal import argrelextrema

import utils
import numpy as np
import pandas as pd
from typing import Optional

WINDOW_SIZE = 240


class PeakModel(Model):

    def __init__(self):
        super()
        self.segments = []
        self.ipeaks = []
        self.state = {
            'confidence': 1.5,
            'convolve_max': 570000
        }

    def fit(self, dataframe: pd.DataFrame, segments: list, cache: Optional[AnalyticUnitCache]) -> AnalyticUnitCache:
        if type(cache) is AnalyticUnitCache:
            self.state = cache

        self.segments = segments
        data = dataframe['value']

        confidences = []
        convolve_list = []
        for segment in segments:
            if segment['labeled']:
                segment_from_index = utils.timestamp_to_index(dataframe, pd.to_datetime(segment['from'], unit='ms'))
                segment_to_index = utils.timestamp_to_index(dataframe, pd.to_datetime(segment['to'], unit='ms'))

                segment_data = data[segment_from_index: segment_to_index + 1]
                if len(segment_data) == 0:
                    continue
                segment_min = min(segment_data)
                segment_max = max(segment_data)
                confidences.append(0.2 * (segment_max - segment_min))
                flat_segment = segment_data.rolling(window=5).mean()
                flat_segment = flat_segment.dropna()
                segment_max_index = flat_segment.idxmax()  # + segment['start']
                self.ipeaks.append(segment_max_index)
                labeled_drop = data[segment_max_index - WINDOW_SIZE: segment_max_index + WINDOW_SIZE]
                labeled_min = min(labeled_drop)
                for value in labeled_drop:
                    value = value - labeled_min
                convolve = scipy.signal.fftconvolve(labeled_drop, labeled_drop)
                convolve_list.append(max(convolve))

        if len(confidences) > 0:
            self.state['confidence'] = float(min(confidences))
        else:
            self.state['confidence'] = 1.5

        if len(convolve_list) > 0:
            self.state['convolve_max'] = float(max(convolve_list))
        else:
            self.state['convolve_max'] = 570000

        return self.state

    def do_predict(self, dataframe: pd.DataFrame):
        data = dataframe['value']
        window_size = 24
        all_maxs = argrelextrema(np.array(data), np.greater)[0]

        extrema_list = []
        for i in utils.exponential_smoothing(data + self.state['confidence'], 0.02):
            extrema_list.append(i)

        segments = []
        for i in all_maxs:
            if data[i] > extrema_list[i]:
                segments.append(i)

        filtered = self.__filter_prediction(segments, data)
        # TODO: convert from ns to ms more proper way (not dividing by 10^6)
        return [(dataframe['timestamp'][x - 1].value / 1000000, dataframe['timestamp'][x + 1].value / 1000000) for x in filtered]

    def __filter_prediction(self, segments: list, data: list) -> list:
        delete_list = []
        variance_error = int(0.004 * len(data))
        if variance_error > 100:
            variance_error = 100
        for i in range(1, len(segments)):
            if segments[i] < segments[i - 1] + variance_error:
                delete_list.append(segments[i])
        for item in delete_list:
            segments.remove(item)

        delete_list = []
        if len(segments) == 0 or len(self.ipeaks) == 0:
            return []

        pattern_data = data[self.ipeaks[0] - WINDOW_SIZE: self.ipeaks[0] + WINDOW_SIZE]
        for segment in segments:
            if segment > WINDOW_SIZE:
                convol_data = data[segment - WINDOW_SIZE: segment + WINDOW_SIZE]
                conv = scipy.signal.fftconvolve(pattern_data, convol_data)
                if max(conv) > self.state['convolve_max'] * 1.2 or max(conv) < self.state['convolve_max'] * 0.8:
                    delete_list.append(segment)
            else:
                delete_list.append(segment)
        # TODO: implement filtering
        # for item in delete_list:
        #     segments.remove(item)

        return set(segments)
