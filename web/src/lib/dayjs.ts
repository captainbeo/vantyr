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
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
// Interface language codes -> dayjs locale module names.
import 'dayjs/locale/ar'
import 'dayjs/locale/de'
import 'dayjs/locale/es'
import 'dayjs/locale/fr'
import 'dayjs/locale/ja'
import 'dayjs/locale/nl'
import 'dayjs/locale/ru'
import 'dayjs/locale/tr'
import 'dayjs/locale/vi'
import 'dayjs/locale/zh-cn'
import 'dayjs/locale/zh-tw'

dayjs.extend(relativeTime)

// Relative timestamps (fromNow) follow the interface language; the dayjs
// global locale is switched together with the html lang/dir attributes.
export function applyDayjsLocale(language: string) {
  const map: Record<string, string> = {
    zhCN: 'zh-cn',
    zhTW: 'zh-tw',
  }
  const locale = map[language] ?? language
  if (locale === dayjs.locale()) return
  if (!dayjs.locale(locale)) dayjs.locale('en')
}

export default dayjs
