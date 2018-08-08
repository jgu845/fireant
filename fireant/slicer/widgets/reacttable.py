from collections import OrderedDict

import numpy as np
import pandas as pd

from fireant.formats import (
    RAW_VALUE,
    TOTALS_VALUE,
)
from fireant.utils import (
    format_dimension_key,
    format_metric_key,
    getdeepattr,
    setdeepattr,
)
from .pandas import Pandas
from ..dimensions import (
    DatetimeDimension,
    Dimension,
)
from ..intervals import (
    annually,
    daily,
    hourly,
    monthly,
    quarterly,
    weekly,
)
from ..metrics import Metric
from ..references import (
    reference_key,
    reference_label,
)

DATE_FORMATS = {
    hourly: '%Y-%m-%d %h',
    daily: '%Y-%m-%d',
    weekly: '%Y-%m',
    monthly: '%Y',
    quarterly: '%Y-%q',
    annually: '%Y',
}

metrics = Dimension('metrics', '')
metrics_dimension_key = format_dimension_key(metrics.key)


def map_index_level(index, level, func):
    # If the index is empty, do not do anything
    if 0 == index.size:
        return index

    if isinstance(index, pd.MultiIndex):
        values = index.levels[level]
        return index.set_levels(values.map(func), level)

    assert level == 0

    return index.map(func)


def fillna_index(index, value):
    if isinstance(index, pd.MultiIndex):
        return pd.MultiIndex.from_tuples([[value if pd.isnull(x) else x
                                           for x in row]
                                          for row in index],
                                         names=index.names)

    return index.fillna(value)


def display_value(value, prefix=None, suffix=None, precision=None):
    if isinstance(value, bool):
        value = str(value).lower()

    def format_numeric_value(value):
        if precision is not None and isinstance(value, float):
            return '{:.{precision}f}'.format(value, precision=precision)

        if isinstance(value, int):
            return '{:,}'.format(value)

        return '{}'.format(value)

    return '{prefix}{value}{suffix}'.format(
          prefix=(prefix or ""),
          suffix=(suffix or ""),
          value=format_numeric_value(value),
    )


class ReferenceItem:
    def __init__(self, item, reference):
        if reference is None:
            self.key = item.key
            self.label = item.label
        else:
            self.key = reference_key(item, reference)
            self.label = reference_label(item, reference)

        self.prefix = item.prefix
        self.suffix = item.suffix
        self.precision = item.precision


class TotalsItem:
    key = TOTALS_VALUE
    label = 'Totals'
    prefix = suffix = precision = None


class ReactTable(Pandas):
    """
    This component does not work with react-table out of the box, some customization is needed in order to work with
    the transformed data.

    ```
    // A Custom TdComponent implementation is required by Fireant in order to render display values
    const TdComponent = ({
                           toggleSort,
                           className,
                           children,
                           ...rest
                         }) =>
        <div className={classNames('rt-td', className)} role="gridcell" {...rest}>
            {_.get(children, 'display', children.raw) || <span>&nbsp;</span>}
        </div>;

    const FireantReactTable = ({
                            config, // The payload from fireant
                          }) =>
        <ReactTable columns={config.columns}
                    data={config.data}
                    minRows={0}

                    TdComponent={ DashmoreTdComponent}
                    defaultSortMethod={(a, b, desc) => ReactTableDefaults.defaultSortMethod(a.raw, b.raw, desc)}>
        </ReactTable>;
    ```
    """

    def __init__(self, metric, *metrics: Metric, pivot=(), transpose=False, max_columns=None):
        super(ReactTable, self).__init__(metric, *metrics,
                                         pivot=pivot,
                                         transpose=transpose,
                                         max_columns=max_columns)

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__,
                               ','.join(str(m) for m in self.items))

    def map_display_values(self, df, dimensions):
        """
        WRITEME

        :param df:
        :param dimensions:
        :return:
        """
        dimension_display_values = {}

        for dimension in dimensions:
            f_dimension_key = format_dimension_key(dimension.key)

            if dimension.has_display_field:
                f_display_key = format_dimension_key(dimension.display_key)

                dimension_display_values[f_dimension_key] = \
                    df[f_display_key].groupby(f_dimension_key).first().fillna('null').to_dict()

                del df[f_display_key]

            if hasattr(dimension, 'display_values'):
                dimension_display_values[f_dimension_key] = dimension.display_values

        return dimension_display_values

    @staticmethod
    def format_data_frame(data_frame, dimensions):
        """
        This function prepares the raw data frame for transformation by formatting dates in the index and removing any
        remaining NaN/NaT values. It also names the column as metrics so that it can be treated like a dimension level.

        :param data_frame:
            The result set data frame
        :param dimensions:
        :return:
        """
        for i, dimension in enumerate(dimensions):
            if isinstance(dimension, DatetimeDimension):
                date_format = DATE_FORMATS.get(dimension.interval, DATE_FORMATS[daily])
                data_frame.index = map_index_level(data_frame.index, i, lambda dt: dt.strftime(date_format))

        data_frame.index = fillna_index(data_frame.index, TOTALS_VALUE)
        data_frame.columns.name = metrics_dimension_key

    @staticmethod
    def transform_dimension_column_headers(data_frame, dimensions):
        """
        Convert the un-pivoted dimensions into ReactTable column header definitions.

        :param data_frame:
            The result set data frame
        :param dimensions:
            A list of dimensions in the data frame that are part of the index
        :return:
            A list of column header definitions with the following structure.

            ```
            columns = [{
              Header: 'Column A',
              accessor: 'a',
            }, {
              Header: 'Column B',
              accessor: 'b',
            }]
            ```
        """
        dimension_map = {format_dimension_key(d.key): d
                         for d in dimensions + [metrics]}

        columns = []
        if isinstance(data_frame.index, pd.RangeIndex):
            return columns

        for f_dimension_key in data_frame.index.names:
            dimension = dimension_map[f_dimension_key]

            columns.append({
                'Header': getattr(dimension, 'label', dimension.key),
                'accessor': f_dimension_key,
            })

        return columns

    @staticmethod
    def transform_metric_column_headers(data_frame, item_map, dimension_display_values):
        """
        Convert the metrics into ReactTable column header definitions. This includes any pivoted dimensions, which will
        result in multiple rows of headers.

        :param data_frame:
            The result set data frame
        :param item_map:
            A map to find metrics/operations based on their keys found in the data frame.
        :param dimension_display_values:
            A map for finding display values for dimensions based on their key and value.
        :return:
            A list of column header definitions with the following structure.

            ```
            columns = [{
              Header: 'Column A',
              columns: [{
                Header: 'SubColumn A.0',
                accessor: 'a.0',
              }, {
                Header: 'SubColumn A.1',
                accessor: 'a.1',
              }]
            }, {
              Header: 'Column B',
              columns: [
                ...
              ]
            }]
            ```
        """

        def get_header(column_value, f_dimension_key, is_totals):
            if f_dimension_key == metrics_dimension_key or is_totals:
                item = item_map[column_value]
                return getattr(item, 'label', item.key)

            return getdeepattr(dimension_display_values, (f_dimension_key, column_value), column_value)

        def _make_columns(columns_frame, previous_levels=()):
            """
            This function recursively creates the individual column definitions for React Table with the above tree
            structure depending on how many index levels there are in the columns.

            :param columns_frame:
                A data frame representing the columns of the result set data frame.
            :param previous_levels:
                A tuple containing the higher level index level values used for building the data accessor path
            """
            f_dimension_key = columns_frame.index.names[0]

            # Group the columns if they are multi-index so we can get the proper sub-column values. This will yield
            # one group per dimension value with the group data frame containing only the relevant sub-columns
            groups = columns_frame.groupby(level=0) \
                if isinstance(columns_frame.index, pd.MultiIndex) else \
                [(level, None) for level in columns_frame.index]

            columns = []
            for column_value, group in groups:
                is_totals = TOTALS_VALUE == column_value

                # All column definitions have a header
                column = {'Header': get_header(column_value, f_dimension_key, is_totals)}

                levels = previous_levels + (column_value,)
                if group is not None:
                    # If there is a group, then drop this index level from the group data frame and recurse to build
                    # sub column definitions
                    next_level_df = group.reset_index(level=0, drop=True)
                    column['columns'] = _make_columns(next_level_df, levels)

                else:
                    # If there is no group, then this is a leaf, or a column header on the bottom row of the table
                    # head. These are effectively the actual columns in the table. All leaf column header definitions
                    # require an accessor for how to acccess data the for that column
                    if hasattr(data_frame, 'name'):
                        # If the metrics column index level was dropped (due to there being a single metric), then the
                        # index level name will be set as the data frame's name.
                        levels += (data_frame.name,)
                    column['accessor'] = '.'.join(levels)

                if is_totals:
                    column['className'] = 'fireant-totals'

                columns.append(column)

            return columns

        column_frame = data_frame.columns.to_frame()
        return _make_columns(column_frame)

    @staticmethod
    def transform_data(data_frame, item_map, dimension_display_values):
        """
        Builds a list of dicts containing the data for ReactTable. This aligns with the accessors set by
        #transform_dimension_column_headers and #transform_metric_column_headers

        :param data_frame:
            The result set data frame
        :param item_map:
            A map to find metrics/operations based on their keys found in the data frame.
        :param dimension_display_values:
            A map for finding display values for dimensions based on their key and value.
        """
        result = []

        for index, series in data_frame.iterrows():
            if not isinstance(index, tuple):
                index = (index,)

            # Get a list of values from the index. These can be metrics or dimensions so it checks in the item map if
            # there is a display value for the value
            index = [item
                     if item not in item_map
                     else getattr(item_map[item], 'label', item_map[item].key)
                     for item in index]

            row = {}

            # Add the index to the row
            for key, value in zip(data_frame.index.names, index):
                if key is None:
                    continue

                data = {RAW_VALUE: value}

                # Try to find a display value for the item. If this is a metric the raw value is replaced with the
                # display value because there is no raw value for a metric label
                display = getdeepattr(dimension_display_values, (key, value))
                if display is not None:
                    data['display'] = display

                row[key] = data

            # Add the values to the row
            for key, value in series.iteritems():
                data = {RAW_VALUE: value}

                # Try to find a display value for the item
                item = item_map.get(key[0] if isinstance(key, tuple) else key)
                display = display_value(value, item.prefix, item.suffix, item.precision) \
                    if item is not None else \
                    value

                if display is not None:
                    data['display'] = display

                setdeepattr(row, key, data)

            result.append(row)

        return result

    def transform(self, data_frame, slicer, dimensions, references):
        """
        Transforms a data frame into a format for ReactTable. This is an object containing attributes `columns` and
        `data` which align with the props in ReactTable with the same name.

        :param data_frame:
            The result set data frame
        :param slicer:
            The slicer that generated the data query
        :param dimensions:
            A list of dimensions that were selected in the data query
        :param references:
            A list of references that were selected in the data query
        :return:
            An dict containing attributes `columns` and `data` which align with the props in ReactTable with the same
            names.
        """
        df_dimension_columns = [format_dimension_key(d.display_key)
                                for d in dimensions
                                if d.has_display_field]
        item_map = OrderedDict([(format_metric_key(reference_key(i, reference)), ReferenceItem(i, reference))
                                for i in self.items
                                for reference in [None] + references])
        df_metric_columns = list(item_map.keys())

        # Add an extra item to map the totals key to it's label
        item_map[TOTALS_VALUE] = TotalsItem

        df = data_frame[df_dimension_columns + df_metric_columns].copy() \
            .fillna(value='NaN') \
            .replace([np.inf, -np.inf], 'Inf')

        dimension_display_values = self.map_display_values(df, dimensions)
        self.format_data_frame(df, dimensions)

        dimension_keys = [format_dimension_key(dimension.key) for dimension in self.pivot]
        df = self.pivot_data_frame(df, dimension_keys, self.transpose)

        dimension_columns = self.transform_dimension_column_headers(df, dimensions)
        metric_columns = self.transform_metric_column_headers(df, item_map, dimension_display_values)
        data = self.transform_data(df, item_map, dimension_display_values)

        return {
            'columns': dimension_columns + metric_columns,
            'data': data,
        }
