/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import type { Row, Table as TanstackTable } from '@tanstack/react-table'
import type * as React from 'react'

export type DataTableColumnClassName = (
  columnId: string,
  kind: 'header' | 'cell'
) => string | undefined

export type DataTablePinnedColumn = {
  columnId: string
  side: 'left' | 'right'
  className?: string
  headerClassName?: string
  cellClassName?: string
}

export type DataTableRenderRowHelpers = {
  getCellClassName: (columnId: string, className?: string) => string | undefined
}

export type DataTableViewProps<TData> = {
  table: TanstackTable<TData>
  isLoading?: boolean
  rows?: Row<TData>[]
  emptyTitle?: string
  emptyDescription?: string
  emptyIcon?: React.ReactNode
  emptyAction?: React.ReactNode
  emptyContent?: React.ReactNode
  emptyCellClassName?: string
  skeletonKeyPrefix?: string
  skeletonRowHeight?: string
  renderRow?: (
    row: Row<TData>,
    helpers: DataTableRenderRowHelpers
  ) => React.ReactNode
  getRowClassName?: (row: Row<TData>) => string | undefined
  getColumnClassName?: DataTableColumnClassName
  pinnedColumns?: DataTablePinnedColumn[]
  applyHeaderSize?: boolean
  tableClassName?: string
  tableHeaderClassName?: string
  tableHeaderRowClassName?: string
  tableBodyClassName?: string
  tableBodyRowClassName?: string
  splitHeader?: boolean
  splitHeaderScrollClassName?: string
  bodyContainerClassName?: string
  containerClassName?: string
  /* Allow `data-*` attributes (e.g. the pricing table's glow hook) through
   * the object-literal path — JSX hyphenated attributes bypass checking,
   * but this object prop does not, and ComponentProps has no data index. */
  containerProps?: Omit<
    React.ComponentProps<'div'>,
    'className' | 'children'
  > & {
    [key: `data-${string}`]: string | undefined
  }
  tableContainerClassName?: string
  colgroup?: React.ReactNode
}
