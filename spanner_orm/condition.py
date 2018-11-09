# python3
# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Used with Model#where and Model#count to help create Spanner queries."""

import abc
import enum

from spanner_orm import error

from google.cloud.spanner_v1.proto import type_pb2


class Segment(enum.Enum):
  """The segment of the SQL query that a Condition belongs to."""
  WHERE = 1
  ORDER_BY = 2
  LIMIT = 3
  JOIN = 4


class Condition(abc.ABC):
  """Base class for specifying conditions in a Spanner query."""

  def __init__(self):
    self.model = None

  def bind(self, model):
    self._validate(model)
    self.model = model

  def params(self):
    if not self.model:
      raise error.SpannerError(
          'Condition must be bound before params is called')
    return self._params()

  @abc.abstractmethod
  def _params(self):
    pass

  @staticmethod
  @abc.abstractmethod
  def segment():
    raise NotImplementedError

  def sql(self):
    if not self.model:
      raise error.SpannerError('Condition must be bound before sql is called')
    return self._sql()

  @abc.abstractmethod
  def _sql(self):
    pass

  def types(self):
    if not self.model:
      raise error.SpannerError('Condition must be bound before types is called')
    return self._types()

  @abc.abstractmethod
  def _types(self):
    pass

  @abc.abstractmethod
  def _validate(self, model):
    pass


class ColumnsEqualCondition(Condition):
  """Used to join records by matching column values."""

  def __init__(self, origin_column, destination_model, destination_column):
    super().__init__()
    self.column = origin_column
    self.destination_model = destination_model
    self.destination_column = destination_column

  def _params(self):
    return {}

  def segment(self):
    return Segment.WHERE

  def _sql(self):
    return '{table}.{column} = {other_table}.{other_column}'.format(
        table=self.model.table(),
        column=self.column,
        other_table=self.destination_model.table(),
        other_column=self.destination_column)

  def _types(self):
    return {}

  def _validate(self, model):
    assert self.column in model.schema()
    origin = model.schema()[self.column]
    assert self.destination_column in self.destination_model.schema()
    dest = self.destination_model.schema()[self.destination_column]

    assert (origin.field_type() == dest.field_type() and
            origin.nullable() == dest.nullable())


class IncludesCondition(Condition):
  """Used to include related models via a relation in a Spanner query."""

  def __init__(self, name, conditions=None):
    super().__init__()
    self.name = name
    self._conditions = conditions or []
    self.relation = None

  def bind(self, model):
    super().bind(model)
    self.relation = self.model.relations()[self.name]

  def conditions(self):
    if not self.relation:
      raise error.SpannerError(
          'Condition must be bound before conditions is called')
    return self.relation.conditions() + self._conditions

  def destination(self):
    if not self.relation:
      raise error.SpannerError(
          'Condition must be bound before destination is called')
    return self.relation.destination()

  def relation_name(self):
    return self.name

  def _params(self):
    return {}

  @staticmethod
  def segment():
    return Segment.JOIN

  def _sql(self):
    return ''

  def _types(self):
    return {}

  def _validate(self, model):
    assert self.name in model.relations()
    other_model = model.relations()[self.name].destination()
    for condition in self._conditions:
      condition._validate(other_model)  # pylint: disable=protected-access


class LimitCondition(Condition):
  """Used to specify a LIMIT condition in a Spanner query"""
  LIMIT_KEY = 'limit'
  OFFSET_KEY = 'offset'

  def __init__(self, limit, offset=0):
    super().__init__()
    for value in [limit, offset]:
      if not isinstance(value, int):
        raise error.SpannerError(
            '{value} is not of type int'.format(value=value))

    self.limit = limit
    self.offset = offset

  def _params(self):
    params = {self.LIMIT_KEY: self.limit}
    if self.offset:
      params[self.OFFSET_KEY] = self.offset
    return params

  @staticmethod
  def segment():
    return Segment.LIMIT

  def _sql(self):
    if self.offset:
      return 'LIMIT @{limit} OFFSET @{offset}'.format(
          limit=self.LIMIT_KEY, offset=self.OFFSET_KEY)
    return 'LIMIT @{limit}'.format(limit=self.LIMIT_KEY)

  def _types(self):
    types = {self.LIMIT_KEY: type_pb2.Type(code=type_pb2.INT64)}
    if self.offset:
      types[self.OFFSET_KEY] = type_pb2.Type(code=type_pb2.INT64)
    return types

  def _validate(self, model):
    # Validation is independent of model for LIMIT
    del model


class OrderType(enum.Enum):
  ASC = 1
  DESC = 2


class OrderByCondition(Condition):
  """Used to specify an ORDER BY condition in a Spanner query"""

  def __init__(self, *orderings):
    super().__init__()
    for (_, order_type) in orderings:
      if not isinstance(order_type, OrderType):
        raise error.SpannerError(
            '{order} is not of type OrderType'.format(order=order_type))
    self.orderings = orderings

  def _params(self):
    return {}

  def _sql(self):
    orders = []
    for (column, order_type) in self.orderings:
      orders.append('{alias}.{column} {order_type}'.format(
          alias=self.model.column_prefix(),
          column=column,
          order_type=order_type.name))
    return 'ORDER BY {orders}'.format(orders=', '.join(orders))

  @staticmethod
  def segment():
    return Segment.ORDER_BY

  def _types(self):
    return {}

  def _validate(self, model):
    for (column, _) in self.orderings:
      assert column in model.schema()


class ComparisonCondition(Condition):
  """Used to specify a comparison between a column and a value in the WHERE"""
  _segment = Segment.WHERE

  def __init__(self, column, value):
    super().__init__()
    self.column = column
    self.value = value

  @staticmethod
  @abc.abstractmethod
  def operator():
    raise NotImplementedError

  def _params(self):
    return {self.column: self.value}

  @staticmethod
  def segment():
    return Segment.WHERE

  def _sql(self):
    return '{alias}.{column} {operator} @{column}'.format(
        alias=self.model.column_prefix(),
        column=self.column,
        operator=self.operator())

  def _types(self):
    return {self.column: self.model.schema()[self.column].grpc_type()}

  def _validate(self, model):
    schema = model.schema()
    assert self.column in schema
    assert self.value is not None
    schema[self.column].validate(self.value)


class GreaterThanCondition(ComparisonCondition):

  @staticmethod
  def operator():
    return '>'


class GreaterThanOrEqualCondition(ComparisonCondition):

  @staticmethod
  def operator():
    return '>='


class LessThanCondition(ComparisonCondition):

  @staticmethod
  def operator():
    return '<'


class LessThanOrEqualCondition(ComparisonCondition):

  @staticmethod
  def operator():
    return '<='


class ListComparisonCondition(ComparisonCondition):
  """Used to compare between a column and a list of values"""

  def _sql(self):
    return '{alias}.{column} {operator} UNNEST(@{column})'.format(
        alias=self.model.column_prefix(),
        column=self.column,
        operator=self.operator())

  def _types(self):
    return {self.column: self.model.schema()[self.column].grpc_list_type()}

  def _validate(self, model):
    schema = model.schema()
    assert isinstance(self.value, list)
    assert self.column in schema
    for value in self.value:
      schema[self.column].validate(value)


class InListCondition(ListComparisonCondition):

  @staticmethod
  def operator():
    return 'IN'


class NotInListCondition(ListComparisonCondition):

  @staticmethod
  def operator():
    return 'NOT IN'


class NullableComparisonCondition(ComparisonCondition):
  """Used to compare between a nullable column and a value or None"""

  def is_null(self):
    return self.value is None

  @staticmethod
  @abc.abstractmethod
  def nullable_operator():
    raise NotImplementedError

  def _params(self):
    if self.is_null():
      return {}
    return super()._params()

  def _sql(self):
    if self.is_null():
      return '{alias}.{column} {operator} NULL'.format(
          alias=self.model.column_prefix(),
          column=self.column,
          operator=self.nullable_operator())
    return super()._sql()

  def _types(self):
    if self.is_null():
      return {}
    return super()._types()

  def _validate(self, model):
    schema = model.schema()
    assert self.column in schema
    schema[self.column].validate(self.value)


class EqualityCondition(NullableComparisonCondition):
  """Represents an equality comparison in a Spanner query"""

  def __eq__(self, obj):
    return isinstance(obj, EqualityCondition) and self.value == obj.value

  def nullable_operator(self):
    return 'IS'

  @staticmethod
  def operator():
    return '='


class InequalityCondition(NullableComparisonCondition):

  @staticmethod
  def nullable_operator():
    return 'IS NOT'

  @staticmethod
  def operator():
    return '!='


def columns_equal(origin_column, dest_model, dest_column):
  return ColumnsEqualCondition(origin_column, dest_model, dest_column)


def equal_to(column, value):
  return EqualityCondition(column, value)


def greater_than(column, value):
  return GreaterThanCondition(column, value)


def greater_than_or_equal_to(column, value):
  return GreaterThanOrEqualCondition(column, value)


def includes(relation, conditions=None):
  return IncludesCondition(relation, conditions)


def in_list(column, value):
  return InListCondition(column, value)


def less_than(column, value):
  return LessThanCondition(column, value)


def less_than_or_equal_to(column, value):
  return LessThanOrEqualCondition(column, value)


def limit(value, offset=0):
  return LimitCondition(value, offset=offset)


def not_equal_to(column, value):
  return InequalityCondition(column, value)


def not_greater_than(column, value):
  return less_than_or_equal_to(column, value)


def not_in_list(column, value):
  return NotInListCondition(column, value)


def not_less_than(column, value):
  return greater_than_or_equal_to(column, value)


def order_by(*orderings):
  return OrderByCondition(*orderings)