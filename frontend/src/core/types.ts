/** Aurora v2 · 前端用到的实体类型（字段以 gl/api.py 的投影为准，全部可选容错）。 */
export interface GameImage {
  url: string
  thumb?: string
  kind?: string
  label?: string
}

export interface Game {
  id: string
  name: string
  name_cn?: string
  name_original?: string
  steam_name?: string
  exe?: string
  exe_name?: string
  dir?: string
  running?: boolean
  missing?: boolean
  favorite?: boolean
  status?: string
  locale_enabled?: boolean
  metadata_state?: string
  metadata_note?: string
  queries?: string[]
  query_used?: string
  developers?: string[]
  publishers?: string[]
  genres?: string[]
  categories?: string[]
  release_date?: string
  rating?: string
  metacritic?: number | string
  description?: string
  description_original?: string
  description_translated?: string
  about?: string
  cover?: string
  cover_sources?: string[]
  custom_cover?: string
  custom_icon?: string
  header_image?: string
  logo?: string
  images?: GameImage[]
  background?: string
  background_kind?: string
  bg_scale?: number
  bg_x?: number
  bg_y?: number
  play_time?: number
  play_count?: number
  last_played?: number
  session_started_at?: number
  play_pid?: number
  sessions?: { started_at: number; seconds: number }[]
  bookshelf_ids?: string[]
  data_source?: string
  source_id?: string
  source_url?: string
  store_url?: string
  match_source?: string
  match_score?: number
  appid?: number | string
  launch_args?: string
  [key: string]: any
}

export interface Shelf {
  id: string
  name: string
  count?: number
  order?: number
}

export interface Scope {
  type: "all" | "unfiled" | "fav" | "shelf" | "status" | "dev" | string
  value: string
}

export interface RingReadout {
  float: number
  target: number
  drag: boolean
  focus: string | null
  keys: string[]
}
