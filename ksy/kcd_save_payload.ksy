meta:
  id: kcd_save_payload
  title: Kingdom Come Deliverance (1) save game payload (decompressed .whs)
  application: "Kingdom Come: Deliverance (Warhorse Studios, CryEngine)"
  file-extension: bin
  ks-version: '0.10'
  endian: le
  encoding: UTF-8
doc: |
  Decompressed payload of a Kingdom Come: Deliverance (1) `.whs` save file.

  A `.whs` file is a chain of zlib blocks followed by an MD5 footer (see
  kcd_whs.ksy). Chunks cross block boundaries, so this spec must be applied to
  the concatenated, decompressed blocks: run `whs_decompress.py` on the save
  and open the resulting `.payload.bin` file with this spec.

  The payload is a tree of chunks: `u2 id`, `u4 len_body`, then `len_body`
  bytes. What the body contains depends on the id (see the `chunk_id` enum);
  ids that are not described here are kept as raw bytes and can be skipped
  thanks to their length. Never rely on chunk order or presence: some chunks
  are optional (mod list, switch save number, active dynamic events) and
  patches add new ones (module 29464 appeared with game version 1.9.7/1.9.8).

  Names follow docs/reverse-engineering.md, adapted to the KSY style guide
  (lowercase type names, num_/len_ prefixes for counts and sizes).

  Parses all the saves of one playthrough (game versions 1.9.6 and 1.9.8),
  from the prologue on, in the main world and in Theresa's DLC level.
seq:
  - id: unknown
    type: u4
    doc: 20 in every save.
  - id: chunks
    type: chunk
    repeat: until
    repeat-until: _.id == chunk_id::end_marker or _io.pos >= _io.size - 1
    doc: Normally `header` (501), `body` (500), then the empty `end_marker` (509).
  - id: trailing_byte
    type: u1
    if: not _io.eof
    doc: Varies from save to save with no known meaning (probably uninitialised memory).
types:
  # ------------------------------------------------------------------ generic chunk tree
  chunk:
    seq:
      - id: id
        type: u2
        enum: chunk_id
      - id: len_body
        type: u4
      - id: body
        size: len_body
        type:
          switch-on: id
          cases:
            # containers whose children use their own ids
            'chunk_id::header': header_chunk_list
            'chunk_id::positioned_records': positioned_record_list
            # containers: the body is a list of chunks
            'chunk_id::body': chunk_list
            'chunk_id::modules': chunk_list
            'chunk_id::engine_data': chunk_list
            'chunk_id::preload': chunk_list
            'chunk_id::layer_states': chunk_list
            'chunk_id::module_8080': chunk_list
            'chunk_id::module_8081': chunk_list
            'chunk_id::module_29442': chunk_list
            'chunk_id::module_29443': chunk_list
            'chunk_id::module_29444': chunk_list
            'chunk_id::module_29445': chunk_list
            'chunk_id::module_29451': chunk_list
            'chunk_id::module_29455': chunk_list
            'chunk_id::module_29458': chunk_list
            'chunk_id::dynamic_events': chunk_list
            'chunk_id::active_event': chunk_list
            'chunk_id::souls_and_statistics': chunk_list
            'chunk_id::statistics': chunk_list
            'chunk_id::guid_records': chunk_list
            'chunk_id::script_names': chunk_list
            'chunk_id::unknown_1001': chunk_list
            'chunk_id::unknown_1700': chunk_list
            'chunk_id::unknown_2000': chunk_list
            'chunk_id::unknown_3008': chunk_list
            'chunk_id::unknown_3009': chunk_list
            'chunk_id::unknown_3012': chunk_list
            'chunk_id::unknown_4879': chunk_list
            'chunk_id::unknown_8097': chunk_list
            'chunk_id::unknown_13612': chunk_list
            'chunk_id::unknown_13613': chunk_list
            # containers with a small prefix
            'chunk_id::records_7782': counted_chunk_list
            'chunk_id::souls': counted_chunk_list
            'chunk_id::soul': guid_and_chunks
            'chunk_id::guid_record': guid_and_chunks
            'chunk_id::script_state': script_state
            'chunk_id::event_slot': event_slot
            # structured leaves
            'chunk_id::layer_state': layer_state
            'chunk_id::metadata_string': metadata_string
            'chunk_id::metadata_int': metadata_int
            'chunk_id::engine_section': engine_section
            'chunk_id::stat_record': stat_record
            'chunk_id::world_clock': world_clock
            'chunk_id::soul_identity': soul_identity
            'chunk_id::script_identifiers': string_table
            'chunk_id::script_type_names': string_table
            'chunk_id::unknown_1101': unknown_1101
            'chunk_id::unknown_1102': f4_value
            'chunk_id::event_name': strz_value
            'chunk_id::event_unknown_4979': u4_value
            'chunk_id::event_unknown_4980': u4_value
            'chunk_id::event_unknown_4983': f4_value
            'chunk_id::event_unknown_4984': u8_value
  chunk_list:
    seq:
      - id: chunks
        type: chunk
        repeat: eos
  counted_chunk_list:
    seq:
      - id: num_chunks
        type: u4
      - id: chunks
        type: chunk
        repeat: expr
        repeat-expr: num_chunks
  script_state:
    doc: Chunk 29452.
    seq:
      - id: unknown
        type: u4
        doc: Always 0.
      - id: chunks
        type: chunk
        repeat: eos
  event_slot:
    doc: Chunk 5498, inside dynamic_events (29462), 85 per save.
    seq:
      - id: slot_number
        type: u4
      - id: chunks
        type: chunk
        repeat: eos
  guid_and_chunks:
    seq:
      - id: guid
        size: 16
      - id: chunks
        type: chunk
        repeat: eos

  # ------------------------------------------------------------------ header (chunk 501)
  header_chunk_list:
    seq:
      - id: chunks
        type: header_chunk
        repeat: eos
  header_chunk:
    doc: |
      Same layout as `chunk`, but the ids come from a small numbering of their
      own (see the `header_chunk_id` enum), so they are only decoded here.
      Order: 13, 16, then 14 (only with mods), then 17 (only inside a DLC level).
    seq:
      - id: id
        type: u2
        enum: header_chunk_id
      - id: len_body
        type: u4
      - id: body
        size: len_body
        type:
          switch-on: id
          cases:
            'header_chunk_id::save_info': save_info
            'header_chunk_id::mod_list': mod_list
            'header_chunk_id::unknown_16': u4_value
            'header_chunk_id::switch_save_number': switch_save_number
  save_info:
    doc: Chunk 13. Everything the in-game load menu shows.
    seq:
      - id: save_type
        type: u4
        enum: save_type
      - id: save_number
        type: u4
        doc: |
          One counter shared by all save types (numbered file names reuse it:
          save508.whs...), except "switch" saves, whose number is separate and
          padded to 5 digits in the file name (switch03227.whs).
      - id: unix_time
        type: u8
      - id: level
        type: strz
        doc: |
          "rataje" (the main open world, prologue included), or "rataje_dlc4" (Theresa's part of
          A Woman's Lot, a separate small world).
      - id: description
        type: strz
        doc: |
          Pipe-separated fields:
          save_type|save_number|quest key|objective key|location key|unix time|dd/mm/yyyy hh:mm|play time|
          Keys like "@subchapter_631_name" resolve through the game's text tables
          (Localization/<Language>_xml.pak, text_ui_quest.xml). The play time is
          statistic #81 printed as a float with 6 decimals; the menu truncates it to 0.1 h.
          "@objective_Savename_1" is the "Quest started" label.
      - id: title
        type: strz
        doc: '"quest key|objective key" on permanent saves and on autosaves that have an objective, empty otherwise.'
      - id: unknown_a
        type: u4
        doc: 200 in every save.
      - id: unknown_b
        type: u4
        doc: 200 in every save.
      - id: unknown_flag
        type: u1
        doc: 0 at the start of a new game, 1 at some later point, already during the prologue (meaning unknown).
      - id: num_dlcs
        type: u2
      - id: dlcs
        type: dlc
        repeat: expr
        repeat-expr: num_dlcs
  switch_save_number:
    doc: |
      Header chunk 17, only in saves made inside a DLC level played as another
      character (Theresa in A Woman's Lot). Entering that level first writes a
      "switch" save (type 6) holding the main world; the DLC level's saves
      hold only the DLC's own small world, plus this number. When the DLC
      ends, the game restores the main world from that switch save.
      Confirmed by reloading a save made before the DLC and entering it again:
      the game wrote switch03227.whs, then autosave800.whs with this value = 3227.
    seq:
      - id: value
        type: u4
        doc: Number of the switch save (the NNNNN of switchNNNNN.whs).
  dlc:
    seq:
      - id: dlc_id
        type: u4
      - id: name
        type: strz
        doc: Localised DLC name.
  mod_list:
    doc: Chunk 14, only present when mods are enabled.
    seq:
      - id: num_mods
        type: u4
      - id: mods
        type: mod
        repeat: expr
        repeat-expr: num_mods
  mod:
    seq:
      - id: folder
        type: strz
        doc: Mod folder name; empty fields for a folder without manifest.
      - id: name
        type: strz
      - id: description
        type: strz
      - id: author
        type: strz
      - id: version
        type: strz
      - id: version_again
        type: strz
        doc: Identical to `version` in every save.

  # ------------------------------------------------------------------ preload (chunk 507)
  layer_state:
    doc: |
      Chunk 555, the on/off state of one level layer. The prologue is not a
      separate map: it is the same level with other layers on, e.g. the
      unburnt Skalitz is `q_skalitz_normal` (later `q_skalitz_burned`).
    seq:
      - id: name
        type: strz
      - id: enabled
        type: u1

  # ------------------------------------------------------------------ engine data (chunk 503)
  metadata_string:
    doc: |
      Chunk 8359, CryEngine ISaveGame::AddMetadata(tag, string). Note that
      "build" is the executable's file version, not the game version shown in
      the menu.
    seq:
      - id: name
        type: strz
      - id: value
        type: strz
  metadata_int:
    doc: |
      Chunk 8360, CryEngine ISaveGame::AddMetadata(tag, int). "version" is 34 and
      "Bit" is the pointer size (64).
    seq:
      - id: name
        type: strz
      - id: value
        type: s4
  engine_section:
    doc: |
      Chunk 8361, CryEngine ISaveGame::AddSection(name): Timer, TerrainState,
      GameTokens, ViewSystem, FlowSystem, MatFX, GameState.
    seq:
      - id: name
        type: strz
      - id: data
        type: typed_stream
        size-eos: true
  typed_stream:
    doc: |
      Parsed lazily (open `values` to read it): GameState alone holds about
      a million values.
    instances:
      values:
        pos: 0
        type: typed_value
        repeat: eos
  typed_group:
    seq:
      - id: items
        type: typed_value
        repeat: until
        repeat-until: _.type == value_type::end_group
        doc: The last item is the end_group marker.
  typed_value:
    doc: |
      One value written by CryEngine's TSerialize. Field names are stored as
      32-bit FNV-1 hashes (h = 0x811C9DC5; for each byte: h = (h * 0x01000193) ^ byte),
      case-sensitive: "curTime" = 0xA0E58D4E, "pos" = 0x407759E5.
      Optional fields are simply omitted (e.g. "rot" when it is the identity).
    seq:
      - id: type
        type: u1
        enum: value_type
        valid:
          any-of:
            - value_type::begin_group
            - value_type::end_group
            - value_type::string16
            - value_type::boolean
            - value_type::float32
            - value_type::vec2
            - value_type::vec3
            - value_type::quat
            - value_type::ang3
            - value_type::int8
            - value_type::int16
            - value_type::int32
            - value_type::int64
            - value_type::uint8
            - value_type::uint16
            - value_type::uint32
            - value_type::uint64
            - value_type::script_value
            - value_type::time_value
      - id: name_hash
        type: u4
        enum: field_name
        if: type != value_type::end_group
        doc: |
          Shown with its name when known: the field_name enum is generated by
          build_field_names.py from the game's WHGame.dll (the save itself only
          stores the hashes). The enum doc holds the exact original spelling.
      - id: value_string
        type: str16
        if: type == value_type::string16
      - id: value_bool
        type: u1
        if: type == value_type::boolean
      - id: value_float
        type: f4
        if: type == value_type::float32
      - id: value_vec2
        type: vec2
        if: type == value_type::vec2
      - id: value_vec3
        type: vec3
        if: type == value_type::vec3 or type == value_type::ang3
      - id: value_quat
        type: quat
        if: type == value_type::quat
      - id: value_int8
        type: s1
        if: type == value_type::int8
      - id: value_int16
        type: s2
        if: type == value_type::int16
      - id: value_int32
        type: s4
        if: type == value_type::int32
      - id: value_int64
        type: s8
        if: type == value_type::int64
      - id: value_uint8
        type: u1
        if: type == value_type::uint8
      - id: value_uint16
        type: u2
        if: type == value_type::uint16
      - id: value_uint32
        type: u4
        if: type == value_type::uint32
      - id: value_uint64
        type: u8
        if: type == value_type::uint64
      - id: value_script
        type: script_value(false)
        if: type == value_type::script_value
      - id: value_time
        type: s8
        if: type == value_type::time_value
        doc: CTimeValue, in 1/100000 s.
      - id: children
        type: typed_group
        if: type == value_type::begin_group
  str16:
    seq:
      - id: len_value
        type: u2
      - id: value
        type: str
        size: len_value
  vec2:
    seq:
      - id: x
        type: f4
      - id: y
        type: f4
  vec3:
    seq:
      - id: x
        type: f4
      - id: y
        type: f4
      - id: z
        type: f4
  quat:
    seq:
      - id: x
        type: f4
      - id: y
        type: f4
      - id: z
        type: f4
      - id: w
        type: f4
  script_value:
    doc: CryEngine ScriptAnyValue.
    params:
      - id: is_key
        type: bool
    seq:
      - id: kind
        type: u1
        enum: script_kind
        valid:
          any-of:
            - script_kind::nil
            - script_kind::boolean
            - script_kind::handle
            - script_kind::number
            - script_kind::string16
            - script_kind::table
            - script_kind::vector
      - id: boolean
        type: u1
        if: kind == script_kind::boolean
      - id: handle
        type: u8
        if: kind == script_kind::handle
        doc: |
          Low 32 bits: an id of unknown kind, not an entity id of GameState (only
          3 distinct values seen, nearly always 0x04680F84). High 32 bits are always 0x0B000000.
      - id: number_key
        type: s4
        if: kind == script_kind::number and is_key
        doc: Numbers used as table keys (array indices 1..n) are stored as int32.
      - id: number
        type: f4
        if: kind == script_kind::number and not is_key
      - id: string
        type: str16
        if: kind == script_kind::string16
      - id: table
        type: script_table
        if: kind == script_kind::table
      - id: vector
        type: vec3
        if: kind == script_kind::vector
        doc: Assumed from CryEngine; never seen in any save.
  script_table:
    seq:
      - id: unknown
        type: u1
        doc: 5 in every save.
      - id: num_pairs
        type: u4
      - id: pairs
        type: script_pair
        repeat: expr
        repeat-expr: num_pairs
  script_pair:
    seq:
      - id: key
        type: script_value(true)
      - id: value
        type: script_value(false)

  # ------------------------------------------------------------------ modules (chunk 502)
  soul_identity:
    doc: |
      Chunk 4866, inside a soul (4446). A new game's souls (2,661) all stay,
      even after death; events and animals add souls that come and go.
    seq:
      - id: guid
        size: 16
        doc: Same GUID as the enclosing soul.
      - id: name
        type: strz
        doc: e.g. "rych_stepan", "_Sheep18".
      - id: unknown
        size: 8
  stat_record:
    doc: |
      Chunk 6008, one statistic (keys 1 to 183; most are cumulative over the
      playthrough, but #61, #62 and #89 reset).
      Statistics belong to the playthrough, not to a world: they keep counting
      inside a DLC level and are not restored from the "switch" save.
      Names and English labels come from the game's Libs/Tables/rpg/statistic.xml
      (Data/Tables.pak) and text_ui_soul.xml. Known keys: 81 = TimePlayed, "Time
      played in playline" (hours; the load menu truncates it to 0.1), 37 =
      TimeIngame, "World time passed" (ms, shown in the Statistics tab in days
      rounded to 0.1; time skips included, pauses excluded; not the clock, see
      world_clock), 50 = TimeSlept, "Time slept" (ms), 55 = ThreatsSucceded,
      "Intimidation successes", 61/62/89 = CurrentStarvingTime /
      CurrentOvereatTime / CurrentProperDietTime (hidden, ms), 96/97/98 = CurrentMainQuest / LastStatLevelUp / LastSkillLevelUp (hidden,
      text; 97 is already set at the start, before any level-up).
    seq:
      - id: key
        type: u4
      - id: value
        type: stat_value
        if: not _io.eof
        doc: Absent for a few keys.
  stat_value:
    seq:
      - id: id
        type: u2
        enum: stat_value_type
      - id: len_body
        type: u4
      - id: body
        size: len_body
        type:
          switch-on: id
          cases:
            'stat_value_type::integer_sum': stat_int32
            'stat_value_type::decimal_sum': stat_float64
            'stat_value_type::play_time': stat_flagged_float64
            'stat_value_type::string': strz_value
            'stat_value_type::distinct_guid': stat_guid_list
            'stat_value_type::distinct_uint': stat_uint32_list
            'stat_value_type::integer_max_proxy': u4_value
            'stat_value_type::script': u4_value
            'stat_value_type::quest': u4_value
            'stat_value_type::world_time': stat_time
            'stat_value_type::world_time_sampling': stat_time
            'stat_value_type::world_time_reset_sampling': stat_time
  stat_int32:
    seq:
      - id: value
        type: s4
  stat_float64:
    seq:
      - id: value
        type: f8
  stat_flagged_float64:
    seq:
      - id: flag
        type: u1
      - id: value
        type: f8
  stat_guid_list:
    seq:
      - id: num_guids
        type: u4
      - id: guids
        size: 16
        repeat: expr
        repeat-expr: num_guids
  stat_uint32_list:
    seq:
      - id: num_values
        type: u4
      - id: values
        type: u4
        repeat: expr
        repeat-expr: num_values
  stat_time:
    seq:
      - id: inner_id
        type: u2
        valid: 26852
      - id: len_inner
        type: u4
        valid: 9
      - id: flag
        type: u1
      - id: value
        type: u8
        doc: In-game milliseconds.
  world_clock:
    doc: |
      Chunk 13617, inside souls_and_statistics (29463), 34 bytes.
      Each level has its own clock: Theresa's DLC level starts at 08:00 on day 0,
      and leaving it restores the main world's clock from the "switch" save.
    seq:
      - id: clock
        type: u8
        doc: |
          In-game clock, in ms since midnight of day 0: a new game starts at
          10:00 (36,000,000). Checked in game: 10:00 in the first save of two
          playthroughs, 16:23 for a save holding day 199, 16:22:53.
      - id: unknown_counter_a
        type: u8
        doc: |
          World time at normal speed, in ms: grows by the in-game time elapsed
          divided by unknown_float (15). So, unlike the play time (statistic
          #81), it stops during pauses and saves, and races ahead during sleep
          (1.44 times the play time at 204 h). Seems to also count loading.
          Exceptions: it grows at the start of the prologue, where the clock is
          frozen at 10:00, and over a playthrough it misses some of the clock's
          advances (about 380 of 4,800 in-game hours).
      - id: unknown_float
        type: f4
        doc: |
          15.0 in every save. Probably the time scale (in-game seconds per real
          second): the two counters grow by the in-game time elapsed divided by it.
      - id: unknown_flag_a
        type: u1
        doc: 1 in a single save (27 h of play), else 0.
      - id: unknown_hours
        type: f4
        doc: |
          12.0 in the first ~5 h of play, 7.5 from ~27 h to ~98 h, else 0.0.
      - id: unknown_flag_b
        type: u1
        doc: 1 in the first ~5 h of play, in one save at 27 h and in Theresa's DLC level, else 0.
      - id: unknown_counter_b
        type: u8
        doc: Like unknown_counter_a (in ms), probably without loading time.
  string_table:
    doc: Chunks 2100 (script identifiers) and 2101 (script type names) of the script state.
    seq:
      - id: unknown
        type: u1
        doc: 0 in every save.
      - id: entries
        type: string_table_entry
        repeat: until
        repeat-until: _io.pos >= _io.size - 2
        if: _io.size > 3
      - id: num_entries
        type: u2
  string_table_entry:
    seq:
      - id: index
        type: u2
        doc: 0, 1, 2... in order.
      - id: text
        type: strz
  positioned_record_list:
    seq:
      - id: chunks
        type: positioned_record_chunk
        repeat: eos
  positioned_record_chunk:
    doc: |
      Same layout as `chunk`. Every item of chunk 1000 has id 0 (up to 68 per
      save), so the id looks like a placeholder rather than a chunk type.
    seq:
      - id: id
        type: u2
        valid: 0
      - id: len_body
        type: u4
      - id: body
        size: len_body
        type: positioned_record
  positioned_record:
    doc: Item of positioned_records (1000). Meaning unknown; persists across saves.
    seq:
      - id: position
        type: vec3
        doc: World position.
      - id: unknown_float
        type: f4
        doc: |
          3.25 most often; also 0.05 and multiples of 0.25 up to 3.0 (the DLC
          level uses 0.5 to 1.25).
      - id: unknown
        type: u4
        repeat: expr
        repeat-expr: 4
  unknown_1101:
    doc: Zero in most saves; set in about one save in five, of every type.
    seq:
      - id: unknown_a
        type: u4
        doc: 1 or 2 when set.
      - id: unknown_b
        type: f4
      - id: unknown_c
        size: 4
        doc: Reads as a plausible f32 where set (0.7, -0.017...).

  # ------------------------------------------------------------------ small value wrappers
  u4_value:
    seq:
      - id: value
        type: u4
  u8_value:
    seq:
      - id: value
        type: u8
  f4_value:
    seq:
      - id: value
        type: f4
  strz_value:
    seq:
      - id: value
        type: strz

enums:
  chunk_id:
    487: unknown_487
    500: body
    501: header
    502: modules
    503: engine_data
    507: preload
    509: end_marker
    555: layer_state
    778: guid_record
    1000: positioned_records
    1001: unknown_1001
    1100: unknown_1100
    1101: unknown_1101
    1102: unknown_1102
    1700: unknown_1700
    2000: unknown_2000
    2100: script_identifiers
    2101: script_type_names
    2102: script_unknown_2102
    3002: records_7782
    3003: guid_records
    3008: unknown_3008
    3009: unknown_3009
    3010: layer_states
    3011: unknown_3011
    3012: unknown_3012
    3214: script_names
    4446: soul
    4866: soul_identity
    4879: unknown_4879
    4979: event_unknown_4979
    4980: event_unknown_4980
    4981: event_name
    4983: event_unknown_4983
    4984: event_unknown_4984
    5498: event_slot
    5499: active_event
    6008: stat_record
    7782: record_7782
    8080: module_8080
    8081: module_8081
    8097: unknown_8097
    8359: metadata_string
    8360: metadata_int
    8361: engine_section
    13609: souls
    13611: unknown_13611
    13612: unknown_13612
    13613: unknown_13613
    13614: unknown_13614
    13615: statistics
    13616: unknown_13616
    13617: world_clock
    29442: module_29442
    29443: module_29443
    29444: module_29444
    29445: module_29445
    29447: module_29447
    29451: module_29451
    29452: script_state
    29455: module_29455
    29458: module_29458
    29459: module_29459
    29462: dynamic_events
    29463: souls_and_statistics
    29464: module_29464
  header_chunk_id:
    13: save_info
    14: mod_list
    16: unknown_16
    17: switch_save_number
  save_type:
    0: permanent
    1: autosave
    2: manual
    5: exit
    6: switch  # the main world, saved when entering a DLC level (see `switch_save_number`)
  value_type:
    0x00: begin_group
    0x01: end_group
    0x02: string16
    0x03: boolean
    0x04: float32
    0x05: vec2
    0x06: vec3
    0x07: quat
    0x08: ang3
    0x09: int8
    0x0a: int16
    0x0b: int32
    0x0c: int64
    0x0d: uint8
    0x0e: uint16
    0x0f: uint32
    0x10: uint64
    0x11: script_value
    0x12: time_value
    0x13: net_object_id
    0x14: xml_node_ref
  script_kind:
    0: any
    1: nil
    2: boolean
    3: handle
    4: number
    5: string16
    6: table
    7: function
    8: userdata
    9: vector
  stat_value_type:
    # the statistic's type in the game's Libs/Tables/rpg/statistic.xml
    14223: integer_sum
    14224: decimal_sum
    14225: distinct_guid
    14226: distinct_uint
    14227: integer_proxy
    14228: decimal_proxy
    14229: integer_max_proxy
    14230: world_time
    14232: play_time
    14234: world_time_sampling
    14235: world_time_reset_sampling
    14236: script
    14237: quest
    14238: string
    14239: soul_level
    14242: soul_deriv_stat
  # BEGIN field_name: generated by build_field_names.py from the game's WHGame.dll, do not edit by hand
  field_name:
    0x0377207b: {id: active, doc: "active"}
    0xf18d659f: {id: actor_entity_physics_ignore, doc: "Actor_EntityPhysicsIgnore"}
    0x9bae9c0f: {id: adv_info_end, doc: "AdvInfoEnd"}
    0xb9170aa1: {id: adv_info_speed, doc: "AdvInfoSpeed"}
    0x86e4356c: {id: adv_info_start, doc: "AdvInfoStart"}
    0x6b1edb7f: {id: ai_npc, doc: "AI_NPC"}
    0xa6f55379: {id: ai_object_id, doc: "aiObjectID"}
    0x6b0a7bf1: {id: aim_dir, doc: "aimDir"}
    0xd385779c: {id: angvel, doc: "angvel"}
    0x43aff437: {id: animated_character, doc: "AnimatedCharacter"}
    0xe7fdaec3: {id: animation_eye_direction, doc: "animationEyeDirection"}
    0x64aaf64e: {id: archetype, doc: "archetype"}
    0xbeb709ea: {id: armor_runtime_data, doc: "ArmorRuntimeData"}
    0x54a0264e: {id: at_move_target, doc: "atMoveTarget"}
    0x91366e89: {id: at_target, doc: "atTarget"}
    0x449d8dae: {id: awake, doc: "awake"}
    0xae82b885: {id: b_count_per_unit, doc: "bCountPerUnit"}
    0xcfcf898e: {id: b_enable_audio, doc: "bEnableAudio"}
    0xec0624c6: {id: b_has_subst, doc: "bHasSubst"}
    0xc6068f58: {id: b_lod_update_enabled, doc: "bLODUpdateEnabled"}
    0x1b31dd0c: {id: b_register_by_b_box, doc: "bRegisterByBBox"}
    0xc2abdb30: {id: basic_entity, doc: "BasicEntity"}
    0x2c334108: {id: basic_entity_data, doc: "BasicEntityData"}
    0xb6bcba33: {id: basic_entity_data_size, doc: "BasicEntityDataSize"}
    0x31afd5a5: {id: beguid, doc: "beguid"}
    0xe5e212d1: {id: bepguid, doc: "bepguid"}
    0xd203928e: {id: blend_amount, doc: "BlendAmount"}
    0xb9ae1299: {id: blood_zone, doc: "bloodZone"}
    0xff4eb3c5: {id: body_data, doc: "BodyData"}
    0x5a3155ba: {id: box_max, doc: "BoxMax"}
    0x62316234: {id: box_min, doc: "BoxMin"}
    0x7159c1dd: {id: break_events, doc: "BreakEvents"}
    0x2710dfb6: {id: breakable_objects, doc: "BreakableObjects"}
    0xd9115a27: {id: breakage_mem_limit, doc: "BreakageMemLimit"}
    0xd32a81c3: {id: broken2d_chunk_ids, doc: "Broken2dChunkIds"}
    0x9a4c38ed: {id: broken_ent_parts, doc: "BrokenEntParts"}
    0x8864792a: {id: broken_mesh_removals, doc: "BrokenMeshRemovals"}
    0xb7ce474e: {id: broken_veg_parts, doc: "BrokenVegParts"}
    0x6c4ac7df: {id: c_actor, doc: "CActor"}
    0x5e8533db: {id: class_, doc: "class"}
    0xc6d95546: {id: collider_size_max, doc: "colliderSize.Max"}
    0xbed948c8: {id: collider_size_min, doc: "colliderSize.Min"}
    0x5988136e: {id: color_gradient, doc: "ColorGradient"}
    0xdefa95db: {id: color_gradient_count, doc: "ColorGradientCount"}
    0xe4a2ac0b: {id: color_gradient_manager, doc: "ColorGradientManager"}
    0x454d924b: {id: container_count, doc: "ContainerCount"}
    0xaf289042: {id: count, doc: "count"}
    0xa0e58d4e: {id: cur_time, doc: "curTime"}
    0xce40e353: {id: curr_state_id, doc: "currStateId"}
    0xa4f27ddd: {id: decal_count, doc: "DecalCount"}
    0xd88cb516: {id: default_active, doc: "defaultActive"}
    0xe6929972: {id: desired_speed, doc: "DesiredSpeed"}
    0xf0fc7652: {id: desired_speed_f0fc7652, doc: "desiredSpeed"}
    0x82dec1ea: {id: dirt, doc: "dirt"}
    0x8d51dc39: {id: disabled_actions_reqs, doc: "disabledActionsReqs"}
    0x6d7728d0: {id: dq, doc: "dq"}
    0xe29f7e2f: {id: e_attach_form, doc: "eAttachForm"}
    0xe1d19c35: {id: e_attach_type, doc: "eAttachType"}
    0xfaca8a47: {id: editor_entity_link, doc: "editorEntityLink"}
    0x2a50bdfb: {id: effect_name, doc: "effectName"}
    0xb39f00ec: {id: elapsed_time, doc: "ElapsedTime"}
    0x59efef78: {id: entity, doc: "Entity"}
    0x2f60ff43: {id: entity_direction, doc: "entityDirection"}
    0x1cc14f67: {id: entity_guid, doc: "entityGuid"}
    0x30544f57: {id: entity_id, doc: "entityID"}
    0xbfb2a2f5: {id: entity_pool_manager_bookmarks, doc: "EntityPoolManager_Bookmarks"}
    0x283aa4df: {id: entity_properties, doc: "EntityProperties"}
    0x16525fe4: {id: entity_proxies, doc: "EntityProxies"}
    0xd1c9f246: {id: entity_template, doc: "EntityTemplate"}
    0x66691754: {id: event_time, doc: "eventTime"}
    0x3b512318: {id: extension, doc: "Extension"}
    0x4b5e500c: {id: extra_entity_data, doc: "ExtraEntityData"}
    0x9964a93d: {id: eye_dir, doc: "eyeDir"}
    0x7732d68e: {id: eye_pos, doc: "eyePos"}
    0x6456d600: {id: f_count_scale, doc: "fCountScale"}
    0x99f7afcf: {id: f_pulse_period, doc: "fPulsePeriod"}
    0x2a99df30: {id: f_size_scale, doc: "fSizeScale"}
    0x2c42100c: {id: f_speed_scale, doc: "fSpeedScale"}
    0x0f89754a: {id: f_strength, doc: "fStrength"}
    0x5894f338: {id: f_time_scale, doc: "fTimeScale"}
    0xb92125b1: {id: fade_in_time, doc: "FadeInTime"}
    0xcd38c322: {id: fast_travel_enabled, doc: "fastTravelEnabled"}
    0xd208494e: {id: file_path, doc: "FilePath"}
    0x27afe28e: {id: fire_dir, doc: "fireDir"}
    0xe9c4033a: {id: fire_target, doc: "fireTarget"}
    0x68cdf632: {id: flags, doc: "flags"}
    0x2e3a9084: {id: flags2, doc: "flags2"}
    0xb9322ef1: {id: flags_ex, doc: "flagsEx"}
    0xe41e0bfc: {id: flying, doc: "flying"}
    0x3ed7b5ce: {id: game_object, doc: "GameObject"}
    0x254f1938: {id: geom_entity, doc: "GeomEntity"}
    0x738a310d: {id: geometry, doc: "Geometry"}
    0x02cd29b2: {id: global_tokens, doc: "GlobalTokens"}
    0x2e10aaae: {id: guid, doc: "guid"}
    0x6e0e3e8a: {id: has_dfm, doc: "hasDfm"}
    0xee8ae90c: {id: has_joints, doc: "hasJoints"}
    0xdb2d51a3: {id: health, doc: "health"}
    0x633b66cf: {id: hhh, doc: "HHH"}
    0x33240bc5: {id: hierarchy_id, doc: "HierarchyID"}
    0x6cccaac7: {id: horse_inventory_enabled, doc: "horseInventoryEnabled"}
    0x6a5d5eac: {id: human, doc: "Human"}
    0x050c5d76: {id: i, doc: "i"}
    0x85e5dad0: {id: i_game, doc: "IGame"}
    0x3638e154: {id: iam, doc: "IAM"}
    0x687720a6: {id: id, doc: "id"}
    0x51854044: {id: ignored_entity, doc: "ignoredEntity"}
    0x7a8b6348: {id: is_aiming, doc: "isAiming"}
    0x34ca26fc: {id: is_alive, doc: "isAlive"}
    0x34c59708: {id: is_firing, doc: "isFiring"}
    0x6793b0c1: {id: is_vis, doc: "isVis"}
    0x1ff17b6e: {id: item_states, doc: "ItemStates"}
    0x1e07758b: {id: joint, doc: "joint"}
    0xbf926c24: {id: jump_state, doc: "jumpState"}
    0xddc35e16: {id: ladder_guid, doc: "ladderGUID"}
    0xce103945: {id: ladder_type, doc: "ladderType"}
    0x6364da73: {id: last_nav_mesh_pos, doc: "LastNavMeshPos"}
    0x717476d0: {id: layer, doc: "Layer"}
    0xba50663b: {id: layer_desc, doc: "LayerDesc"}
    0x1dbdb769: {id: layer_entities, doc: "LayerEntities"}
    0x6a570903: {id: layers, doc: "Layers"}
    0x1ad5350f: {id: ledge_id, doc: "LedgeId"}
    0xd9b042d8: {id: level_data, doc: "level_data"}
    0x5dfbe887: {id: level_tokens, doc: "LevelTokens"}
    0x087b7935: {id: light_common_editr_properties, doc: "LightCommonEditrProperties"}
    0x6aab4301: {id: link, doc: "Link"}
    0xa2eeca6b: {id: linked_entity, doc: "linkedEntity"}
    0xb8f50ddb: {id: linked_entity_helper, doc: "LinkedEntityHelper"}
    0xec9a7ae0: {id: links, doc: "Links"}
    0xd7b01ef2: {id: loaded_from_level_file, doc: "loadedFromLevelFile"}
    0x84ba76b0: {id: lod_r, doc: "LodR"}
    0x6ad55cda: {id: m_active_profile, doc: "m_ActiveProfile"}
    0xa380a022: {id: m_aim_clamped, doc: "m_aimClamped"}
    0x9528b52b: {id: m_aim_target, doc: "m_aimTarget"}
    0x80db5b2a: {id: m_anim_target_speed, doc: "m_animTargetSpeed"}
    0xded25d1a: {id: m_anim_target_speed_counter, doc: "m_animTargetSpeedCounter"}
    0x24bd1165: {id: m_b_ocean, doc: "m_bOcean"}
    0x738c65bd: {id: m_blend_profile, doc: "m_BlendProfile"}
    0xd002f686: {id: m_blend_weight, doc: "m_BlendWeight"}
    0xb47c8ce0: {id: m_can_call_horse, doc: "m_CanCallHorse"}
    0x823d31ce: {id: m_climb_inertia, doc: "m_ClimbInertia"}
    0x1a85364e: {id: m_current_movement_state, doc: "m_currentMovementState"}
    0x75d37afb: {id: m_current_phys_profile, doc: "m_CurrentPhysProfile"}
    0x952326de: {id: m_distance_sliding, doc: "m_distanceSliding"}
    0x538e0c73: {id: m_e_shadow_mode, doc: "m_eShadowMode"}
    0x93a42d54: {id: m_enter_from_ground, doc: "m_enterFromGround"}
    0x9d9b4d9d: {id: m_enter_from_sprint, doc: "m_enterFromSprint"}
    0x435fc944: {id: m_exit_velocity, doc: "m_exitVelocity"}
    0x783e2186: {id: m_fall_test, doc: "m_FallTest"}
    0x749ffb38: {id: m_first_pre_physics_update, doc: "m_firstPrePhysicsUpdate"}
    0x484d7c66: {id: m_forced_tag_list, doc: "m_forcedTagList"}
    0xafdc138e: {id: m_fraction_between_rungs, doc: "m_FractionBetweenRungs"}
    0xc94661e2: {id: m_fragment_id, doc: "m_FragmentID"}
    0x13a13933: {id: m_k_air_control, doc: "m_kAirControl"}
    0x8bcf0333: {id: m_k_air_resistance, doc: "m_kAirResistance"}
    0x7f3cfcca: {id: m_k_inertia, doc: "m_kInertia"}
    0xd6deffc6: {id: m_k_inertia_accel, doc: "m_kInertiaAccel"}
    0x04e36784: {id: m_ladder_bottom, doc: "m_LadderBottom"}
    0xc86d4194: {id: m_last_time_on_ledge, doc: "m_lastTimeOnLedge"}
    0xed1e525f: {id: m_ledge_blending_m_height_blend_weight, doc: "m_ledgeBlending.m_HeightBlendWeight"}
    0xa3c423cd: {id: m_ledge_blending_m_qt_target_location_q, doc: "m_ledgeBlending.m_qtTargetLocation.q"}
    0xa3c423c8: {id: m_ledge_blending_m_qt_target_location_t, doc: "m_ledgeBlending.m_qtTargetLocation.t"}
    0xd661d892: {id: m_ledge_previous_position, doc: "m_ledgePreviousPosition"}
    0x2862dff7: {id: m_ledge_previous_position_diff, doc: "m_ledgePreviousPositionDiff"}
    0x9e720dc4: {id: m_ledge_speed_multiplier, doc: "m_ledgeSpeedMultiplier"}
    0xb96b097b: {id: m_look_target, doc: "m_lookTarget"}
    0x6a5be8e0: {id: m_moon_rotation_latitude, doc: "m_moonRotationLatitude"}
    0xf2bef9d7: {id: m_moon_rotation_longitude, doc: "m_moonRotationLongitude"}
    0xed57d7ed: {id: m_no_jump_speed, doc: "m_noJumpSpeed"}
    0x7dc02e70: {id: m_num_rungs_from_bottom_position, doc: "m_NumRungsFromBottomPosition"}
    0xacbbe34d: {id: m_on_ledge, doc: "m_onLedge"}
    0xdf6f7503: {id: m_post_serialize_ledge_transition, doc: "m_postSerializeLedgeTransition"}
    0xbb380088: {id: m_pseudo_speed, doc: "m_pseudoSpeed"}
    0x836a7549: {id: m_requested_work_m_work_type, doc: "m_RequestedWork.m_WorkType"}
    0x1f6eb91c: {id: m_scale_settle, doc: "m_ScaleSettle"}
    0x5ef6e325: {id: m_ser_should_ragdollize, doc: "m_SerShouldRagdollize"}
    0x16c45003: {id: m_sliding_start_pos, doc: "m_slidingStartPos"}
    0xdc9043c7: {id: m_sun_rotation_latitude, doc: "m_sunRotationLatitude"}
    0x1607ed3a: {id: m_sun_rotation_longitude, doc: "m_sunRotationLongitude"}
    0xc9b8634f: {id: m_time_flying, doc: "m_timeFlying"}
    0xb7851a27: {id: m_time_force_inertia, doc: "m_timeForceInertia"}
    0x7a43c120: {id: m_time_sliding, doc: "m_timeSliding"}
    0xa0b833ef: {id: m_top_rung_number, doc: "m_TopRungNumber"}
    0xf60fa32e: {id: m_using_aim_ik, doc: "m_usingAimIK"}
    0xa0092f3e: {id: m_using_look_ik, doc: "m_usingLookIK"}
    0xd4efcfec: {id: m_work_action_type, doc: "m_workActionType"}
    0x81f24a4f: {id: mat_layers, doc: "MatLayers"}
    0x6d04d9a2: {id: material, doc: "Material"}
    0xa64a5dd6: {id: maximum_blend_amount, doc: "MaximumBlendAmount"}
    0xc57b7248: {id: mode, doc: "mode"}
    0x7d8db8bf: {id: move_dir, doc: "moveDir"}
    0x2f8b3bf4: {id: name, doc: "name"}
    0x66ab48f9: {id: normal_entity_data, doc: "NormalEntityData"}
    0x2b2b6571: {id: num_bookmarks_dynamic, doc: "numBookmarksDynamic"}
    0xd5b494fc: {id: num_bookmarks_static, doc: "numBookmarksStatic"}
    0xc2916381: {id: num_extensions, doc: "numExtensions"}
    0x0e391ead: {id: num_layers, doc: "numLayers"}
    0x0ae61a12: {id: num_links, doc: "numLinks"}
    0x4ab8d90c: {id: numjoints, doc: "numjoints"}
    0xfddbb3a3: {id: obst_occl_calc_type, doc: "obstOcclCalcType"}
    0x7c57c175: {id: offs_pivot, doc: "offsPivot"}
    0x5f6317d5: {id: parent, doc: "parent"}
    0x1bbf3852: {id: particles, doc: "Particles"}
    0xc8951cd7: {id: pause_start, doc: "PauseStart"}
    0xbb3d5c7b: {id: paused, doc: "Paused"}
    0xc7cddf64: {id: physics_proxy, doc: "PhysicsProxy"}
    0xf1f69e5c: {id: physics_type, doc: "PhysicsType"}
    0x407759e5: {id: pos, doc: "pos"}
    0x4027a7c5: {id: pos_4027a7c5, doc: "Pos"}
    0x429bd9c1: {id: prefix, doc: "Prefix"}
    0xd7812e55: {id: prime_always, doc: "primeAlways"}
    0xeaee064a: {id: proximity_radius, doc: "proximityRadius"}
    0x050c5d6e: {id: q, doc: "q"}
    0xdb47075e: {id: q0changed, doc: "q0changed"}
    0xfb22a24b: {id: qext, doc: "qext"}
    0x5c677be0: {id: quat0, doc: "quat0"}
    0x3c8d7cfe: {id: ragdoll, doc: "Ragdoll"}
    0xe2bcc9df: {id: render_proxy, doc: "RenderProxy"}
    0x4072dc1c: {id: rot, doc: "rot"}
    0xd4cbea23: {id: s_audio_rtpc, doc: "sAudioRTPC"}
    0xe3c7b2c0: {id: saved_entity_count, doc: "savedEntityCount"}
    0x1c706549: {id: scl, doc: "scl"}
    0x79119270: {id: script_data, doc: "ScriptData"}
    0x6847eaa0: {id: script_misc, doc: "ScriptMisc"}
    0x32cbba48: {id: script_proxy, doc: "ScriptProxy"}
    0xf87f2c7a: {id: script_timers, doc: "ScriptTimers"}
    0x6bec59f9: {id: script_update_rate, doc: "scriptUpdateRate"}
    0x4324bf21: {id: sequence_number, doc: "sequenceNumber"}
    0x56e4d503: {id: serializable_ropes, doc: "SerializableRopes"}
    0xfbff4367: {id: serialized_wuid_desc, doc: "SerializedWUIDDesc"}
    0x0b580d3a: {id: simclass, doc: "simclass"}
    0x868936d2: {id: size, doc: "Size"}
    0xd16f3210: {id: smart_object_helpers, doc: "SmartObjectHelpers"}
    0x011fac71: {id: smart_object_type_hi, doc: "SmartObjectType_hi"}
    0x051fb20b: {id: smart_object_type_lo, doc: "SmartObjectType_lo"}
    0x4deb4559: {id: stance, doc: "stance"}
    0x4109323e: {id: stance_size_max, doc: "stanceSize.Max"}
    0x49093eb0: {id: stance_size_min, doc: "stanceSize.Min"}
    0x6731bbbc: {id: start_time, doc: "startTime"}
    0xd2933770: {id: state, doc: "State"}
    0x34e73891: {id: state_flags, doc: "StateFlags"}
    0xfcfb2a81: {id: state_hierarchy, doc: "StateHierarchy"}
    0x5eacc61f: {id: state_id, doc: "StateID"}
    0x91346574: {id: state_jump, doc: "StateJump"}
    0x498231a3: {id: state_ledge, doc: "StateLedge"}
    0x45ede021: {id: state_name, doc: "StateName"}
    0x48ad646d: {id: static_decals, doc: "StaticDecals"}
    0x6eedac5f: {id: terrain_mods, doc: "TerrainMods"}
    0x89ba274f: {id: terrain_state, doc: "TerrainState"}
    0x7ebebfc6: {id: ticks_per_second, doc: "ticksPerSecond"}
    0x9e3669da: {id: time, doc: "time"}
    0x5088393c: {id: timer, doc: "Timer"}
    0x6bbb7a89: {id: timer_count, doc: "timerCount"}
    0xe9421963: {id: timer_id, doc: "timerID"}
    0x02721907: {id: timers, doc: "Timers"}
    0x36463cad: {id: trigger_proxy, doc: "TriggerProxy"}
    0x7430594b: {id: up_dir, doc: "upDir"}
    0xac3968e2: {id: update_order, doc: "UpdateOrder"}
    0xd697d721: {id: update_state, doc: "updateState"}
    0x143f4d1b: {id: usable, doc: "__usable"}
    0xb1efa2c0: {id: user_light_proxy, doc: "UserLightProxy"}
    0x050c5d69: {id: v, doc: "v"}
    0x8f739e9d: {id: value_hi, doc: "ValueHi"}
    0x8b7398c7: {id: value_lo, doc: "ValueLo"}
    0x2a682c06: {id: vel, doc: "vel"}
    0x3a8af34a: {id: vel_requested, doc: "velRequested"}
    0xf31eb59b: {id: version, doc: "Version"}
    0x3b11eccc: {id: view_dist_r, doc: "ViewDistR"}
    0xce992c05: {id: weapon_pos, doc: "weaponPos"}
    0xa4909be7: {id: weapon_set, doc: "weaponSet"}
    0xa20e7b55: {id: whai_entity_cat, doc: "WHAIEntityCat"}
  # END field_name
