# Bulk Test Renaming Rule 7.1 Implementation Plan (Part 4/4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename all violating tests in specified files/directories to follow Rule 7.1 (sentence format).

**Architecture:** Surgical renaming of test functions to follow `test_<behavior>_when_<condition>` or `test_<component>_<behavior>` patterns, ensuring they are full sentences.

**Tech Stack:** Python, pytest, scripts/check_test_names.py

---

### Task 1: Rename tests in `tests/unit/test_slicer.py`

**Files:**
- Modify: `tests/unit/test_slicer.py`

- [ ] **Step 1: Rename violations in `tests/unit/test_slicer.py`**
    - `test_compute_hash_deterministic` -> `test_compute_hash_is_deterministic`
    - `test_manifest_is_hashable` -> `test_manifest_is_hashable_for_set_operations`
    - `test_selects_sections_until_max_tokens` -> `test_selects_sections_until_max_tokens_limit_is_reached`
    - `test_selects_most_recent_under_budget_pressure` -> `test_selects_most_recent_under_budget_pressure_when_needed`
    - `test_recency_packer_sorting_is_deterministic_without_suffixes` -> `test_recency_packer_sorting_is_deterministic_without_numeric_suffixes`
    - `test_write_to_permitted_section_passes` -> `test_write_to_permitted_section_passes_validation`
    - `test_requires_embedding_provider` -> `test_semantic_slicer_requires_embedding_provider`
    - `test_ranks_by_similarity` -> `test_semantic_slicer_ranks_by_similarity_to_query`
    - `test_selects_within_max_tokens_boundary` -> `test_semantic_slicer_selects_within_max_tokens_boundary`
    - `test_keys_without_numeric_suffix_default_to_zero` -> `test_keys_without_numeric_suffix_default_to_zero_index`
    - `test_all_sections_over_budget` -> `test_all_sections_over_budget_results_in_empty_slice`

- [ ] **Step 2: Verify fixes**
    - Run: `python scripts/check_test_names.py tests/unit/test_slicer.py`
    - Expected: No violations for this file.

- [ ] **Step 3: Commit**
    - `git add tests/unit/test_slicer.py`
    - `git commit -m "test: rename slicer tests to sentence format"`

### Task 2: Rename tests in `tests/unit/test_types.py`

**Files:**
- Modify: `tests/unit/test_types.py`

- [ ] **Step 1: Rename violations in `tests/unit/test_types.py`**
    - `test_map_result_applies_function_to_success` -> `test_map_result_applies_function_to_success_payload`
    - `test_map_result_leaves_failure_unchanged` -> `test_map_result_leaves_failure_payload_unchanged`
    - `test_map_result_rollback_success` -> `test_map_result_handles_rollback_success`
    - `test_map_error_applies_function_to_failure` -> `test_map_error_applies_function_to_failure_payload`
    - `test_map_error_leaves_success_unchanged` -> `test_map_error_leaves_success_payload_unchanged`
    - `test_map_error_leaves_rollback_success_unchanged` -> `test_map_error_leaves_rollback_success_payload_unchanged`
    - `test_rollback_success_is_neither_success_nor_failure` -> `test_rollback_success_is_neither_success_nor_failure_type`
    - `test_map_error_ignores_rollback_success` -> `test_map_error_ignores_rollback_success_payload`

- [ ] **Step 2: Verify fixes**
    - Run: `python scripts/check_test_names.py tests/unit/test_types.py`
    - Expected: No violations for this file.

- [ ] **Step 3: Commit**
    - `git add tests/unit/test_types.py`
    - `git commit -m "test: rename types tests to sentence format"`

### Task 3: Rename tests in `tests/unit/test_parallel/`

**Files:**
- Modify: `tests/unit/test_parallel/test_fork_runner.py`
- Modify: `tests/unit/test_parallel/test_types.py`

- [ ] **Step 1: Rename violations in `tests/unit/test_parallel/test_fork_runner.py`**
    - `test_includes_text_and_structured` -> `test_fork_output_includes_text_and_structured_data`
    - `test_fixed_fork_runner_satisfies_agent_runner_protocol` -> `test_fixed_fork_runner_satisfies_agent_runner_protocol_definition`

- [ ] **Step 2: Rename violations in `tests/unit/test_parallel/test_types.py`**
    - `test_strategy_values_match_design_doc` -> `test_strategy_values_match_design_doc_definitions`
    - `test_strategy_is_string_enum` -> `test_parallel_strategy_is_string_enum_type`
    - `test_fork_spec_is_frozen` -> `test_fork_spec_is_frozen_dataclass`
    - `test_passing_fork_result_has_no_failure` -> `test_passing_fork_result_has_no_failure_payload`
    - `test_failing_fork_result_has_no_output` -> `test_failing_fork_result_has_no_output_payload`

- [ ] **Step 3: Verify fixes**
    - Run: `python scripts/check_test_names.py tests/unit/test_parallel/`
    - Expected: No violations for these files.

- [ ] **Step 4: Commit**
    - `git add tests/unit/test_parallel/`
    - `git commit -m "test: rename parallel tests to sentence format"`

### Task 4: Rename tests in `tests/unit/test_runners/`

**Files:**
- Modify: `tests/unit/test_runners/test_crewai.py`
- Modify: `tests/unit/test_runners/test_local_model.py`
- Modify: `tests/unit/test_runners/test_protocol.py`
- Modify: `tests/unit/test_runners/test_registry.py`

- [ ] **Step 1: Rename violations in `tests/unit/test_runners/test_crewai.py`**
    - `test_accepts_agent_without_memory` -> `test_crewai_adapter_accepts_agent_without_memory`

- [ ] **Step 2: Rename violations in `tests/unit/test_runners/test_local_model.py`**
    - `test_strips_trailing_slash_from_base_url` -> `test_local_model_strips_trailing_slash_from_base_url`
    - `test_preserves_url_without_trailing_slash` -> `test_local_model_preserves_url_without_trailing_slash`
    - `test_local_model_adapter_is_frozen` -> `test_local_model_adapter_is_frozen_dataclass`
    - `test_default_adapter_name` -> `test_local_model_has_default_adapter_name`
    - `test_default_timeout` -> `test_local_model_has_default_timeout`
    - `test_build_payload_includes_model_and_messages` -> `test_local_model_build_payload_includes_model_and_messages`

- [ ] **Step 3: Rename violations in `tests/unit/test_runners/test_protocol.py`**
    - `test_fixed_agent_runner_satisfies_protocol` -> `test_fixed_agent_runner_satisfies_protocol_definition`
    - `test_object_without_run_does_not_satisfy_protocol` -> `test_object_without_run_does_not_satisfy_runner_protocol`
    - `test_class_without_async_run_does_not_satisfy_protocol` -> `test_class_without_async_run_does_not_satisfy_runner_protocol`
    - `test_agent_output_is_frozen` -> `test_agent_output_is_frozen_dataclass`
    - `test_context_slice_is_frozen` -> `test_context_slice_is_frozen_dataclass`
    - `test_context_slice_sections_reflects_manifest_reads` -> `test_context_slice_sections_reflects_manifest_reads_filter`
    - `test_context_slice_fields` -> `test_context_slice_has_expected_fields`

- [ ] **Step 4: Rename violations in `tests/unit/test_runners/test_registry.py`**
    - `test_registers_and_retrieves_adapter` -> `test_registry_registers_and_retrieves_adapter_successfully`

- [ ] **Step 5: Verify fixes**
    - Run: `python scripts/check_test_names.py tests/unit/test_runners/`
    - Expected: No violations for these files.

- [ ] **Step 6: Commit**
    - `git add tests/unit/test_runners/`
    - `git commit -m "test: rename runners tests to sentence format"`

### Task 5: Rename tests in `tests/unit/test_context_broker.py`

**Files:**
- Modify: `tests/unit/test_context_broker.py`

- [ ] **Step 1: Rename violations in `tests/unit/test_context_broker.py`**
    - `test_broker_next_envelope_increments_step` -> `test_broker_next_envelope_increments_step_number`

- [ ] **Step 2: Verify fixes**
    - Run: `python scripts/check_test_names.py tests/unit/test_context_broker.py`
    - Expected: No violations for this file.

- [ ] **Step 3: Commit**
    - `git add tests/unit/test_context_broker.py`
    - `git commit -m "test: rename context broker tests to sentence format"`
