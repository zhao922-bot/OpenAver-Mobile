"""Compatibility facade for the split rename planning modules."""

from core.rename_combined_plan import (
    _combined_plan_id,
    _multipart_item_key,
    build_combined_rename_plan,
    execute_combined_rename_plan,
    validate_combined_rename_plan,
)
from core.rename_file_execution import execute_rename_plan
from core.rename_file_plan import build_rename_plan
from core.rename_folder_plan import (
    _folder_plan_id,
    build_folder_rename_plan,
    execute_folder_rename_plan,
)
from core.rename_names import (
    _append_multipart_token,
    _fit_filename_stem,
    _find_repair_video,
    _number_pattern,
    _operation_kind,
    _path_key,
    _sidecar_matches,
    _sidecar_suffix,
    _strip_multipart_token,
    _truncate_utf8,
    _utf8_len,
    canonicalize_source_stem,
    canonicalize_stem,
    multipart_token,
)
from core.rename_shared import (
    _create_directory,
    _delete_directory,
    _is_direct_child,
    _is_source_root,
    _move_file,
    _rebase_path,
    _rebase_path_list,
    _relative_path_under,
    _rename_directory,
    _rename_file,
    _write_manifest,
)
