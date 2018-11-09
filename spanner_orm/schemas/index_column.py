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
"""Model for interacting with Spanner index column schema table."""

from spanner_orm import field
from spanner_orm.schemas import schema


class IndexColumnSchema(schema.Schema):
  """Model for interacting with Spanner index column schema table."""

  __table__ = 'information_schema.index_columns'
  table_catalog = field.Field(field.String)
  table_schema = field.Field(field.String)
  table_name = field.Field(field.String)
  index_name = field.Field(field.String)
  column_name = field.Field(field.String)
  ordinal_position = field.Field(field.Integer, nullable=True)
  column_ordering = field.Field(field.String, nullable=True)
  is_nullable = field.Field(field.String)
  spanner_type = field.Field(field.String)

  @staticmethod
  def primary_index_keys():
    return [
        'table_catalog', 'table_schema', 'table_name', 'index_name',
        'column_name'
    ]