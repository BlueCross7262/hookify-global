#!/usr/bin/env python3
"""Rule evaluation engine for hookify plugin."""

import re
import os
import sys
from functools import lru_cache
from typing import List, Dict, Any, Optional

# Import from local module
from core.config_loader import Rule, Condition


# Cache compiled regexes (max 128 patterns)
@lru_cache(maxsize=128)
def compile_regex(pattern: str) -> re.Pattern:
    """Compile regex pattern with caching.

    Args:
        pattern: Regex pattern string

    Returns:
        Compiled regex pattern
    """
    return re.compile(pattern, re.IGNORECASE)


class RuleEngine:
    """Evaluates rules against hook input data."""

    def __init__(self):
        """Initialize rule engine."""
        # No need for instance cache anymore - using global lru_cache
        pass

    def evaluate_rules(self, rules: List[Rule], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate all rules and return combined results.

        Checks all rules and accumulates matches. Blocking rules take priority
        over warning rules. All matching rule messages are combined.

        Args:
            rules: List of Rule objects to evaluate
            input_data: Hook input JSON (tool_name, tool_input, etc.)

        Returns:
            Response dict with systemMessage, hookSpecificOutput, etc.
            Empty dict {} if no rules match.
        """
        hook_event = input_data.get('hook_event_name', '')
        blocking_rules = []
        warning_rules = []

        for rule in rules:
            if self._rule_matches(rule, input_data):
                if rule.action == 'block':
                    blocking_rules.append(rule)
                else:
                    warning_rules.append(rule)

        # If any blocking rules matched, block the operation
        if blocking_rules:
            messages = [f"**[{r.name}]**\n{r.message}" for r in blocking_rules]
            combined_message = "\n\n".join(messages)

            # 차단 응답을 이벤트별로 분기한다 (공식 스키마 준수).
            if hook_event == 'PreToolUse':
                # PreToolUse는 permissionDecisionReason으로 사유를 전달한다.
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": combined_message
                    }
                }
            elif hook_event in ['PostToolUse', 'Stop', 'UserPromptSubmit']:
                # 나머지 차단 이벤트는 top-level decision/reason을 사용한다.
                return {
                    "decision": "block",
                    "reason": combined_message,
                    "systemMessage": combined_message
                }
            else:
                # 그 외 이벤트는 메시지만 표시한다.
                return {
                    "systemMessage": combined_message
                }

        # If only warnings, show them but allow operation
        if warning_rules:
            messages = [f"**[{r.name}]**\n{r.message}" for r in warning_rules]
            return {
                "systemMessage": "\n\n".join(messages)
            }

        # No matches - allow operation
        return {}

    def _rule_matches(self, rule: Rule, input_data: Dict[str, Any]) -> bool:
        """Check if rule matches input data.

        Args:
            rule: Rule to evaluate
            input_data: Hook input data

        Returns:
            True if rule matches, False otherwise
        """
        # Extract tool information
        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})

        # cwd_scope: 활성 시 cwd가 패턴과 일치하는 워크스페이스에서만 룰을 발동한다.
        # 패턴이 비면(오타·누락) 전역 차단으로 새지 않도록 어디서도 발동하지 않는다(fail-safe).
        if rule.cwd_scope:
            cwd = input_data.get('cwd') or ''
            if not rule.cwd_pattern or not self._regex_match(rule.cwd_pattern, cwd):
                return False

        # cwd_path_scope: 명령 인자의 파일 경로가 cwd 안일 때만 발동(특정 불가 시 skip).
        if rule.cwd_path_scope:
            if not self._command_targets_inside_cwd(tool_input, input_data.get('cwd') or ''):
                return False

        # Check tool matcher if specified
        if rule.tool_matcher:
            if not self._matches_tool(rule.tool_matcher, tool_name):
                return False

        # If no conditions, don't match
        # (Rules must have at least one condition to be valid)
        if not rule.conditions:
            return False

        # All conditions must match
        for condition in rule.conditions:
            if not self._check_condition(condition, tool_name, tool_input, input_data):
                return False

        return True

    def _matches_tool(self, matcher: str, tool_name: str) -> bool:
        """Check if tool_name matches the matcher pattern.

        Args:
            matcher: Pattern like "Bash", "Edit|Write", "*"
            tool_name: Actual tool name

        Returns:
            True if matches
        """
        if matcher == '*':
            return True

        # Split on | for OR matching
        patterns = matcher.split('|')
        return tool_name in patterns

    def _command_targets_inside_cwd(self, tool_input: Dict[str, Any], cwd: str) -> bool:
        """명령 인자 중 cwd 안을 가리키는 파일 경로가 있는지 확인한다.

        구분자(슬래시·역슬래시·~)가 있는 토큰만 경로로 본다. 경로를 특정할 수
        없으면 False, cwd 밖만 가리켜도 False.
        """
        if not cwd:
            return False
        command = tool_input.get('command')
        if not isinstance(command, str) or not command:
            return False
        try:
            root = os.path.normcase(os.path.abspath(cwd))
        except (TypeError, ValueError):
            return False
        for tok in command.split():
            tok = tok.strip('\'"')
            if '/' not in tok and '\\' not in tok and not tok.startswith('~'):
                continue
            if re.match(r'[a-z][a-z0-9+.-]*://', tok, re.IGNORECASE):
                continue  # URL(http://·git:// 등)은 파일 경로 아님
            p = os.path.expanduser(tok)
            if not os.path.isabs(p):
                p = os.path.join(cwd, p)
            try:
                p = os.path.normcase(os.path.abspath(p))
            except (TypeError, ValueError):
                continue
            if p == root or p.startswith(root + os.sep):
                return True
        return False

    def _check_condition(self, condition: Condition, tool_name: str,
                        tool_input: Dict[str, Any], input_data: Dict[str, Any] = None) -> bool:
        """Check if a single condition matches.

        Args:
            condition: Condition to check
            tool_name: Tool being used
            tool_input: Tool input dict
            input_data: Full hook input data (for Stop events, etc.)

        Returns:
            True if condition matches
        """
        # Extract the field value to check
        field_value = self._extract_field(condition.field, tool_name, tool_input, input_data)
        if field_value is None:
            return False

        # Apply operator
        operator = condition.operator
        pattern = condition.pattern

        if operator == 'regex_match':
            return self._regex_match(pattern, field_value)
        elif operator == 'contains':
            return pattern in field_value
        elif operator == 'equals':
            return pattern == field_value
        elif operator == 'not_contains':
            return pattern not in field_value
        elif operator == 'starts_with':
            return field_value.startswith(pattern)
        elif operator == 'ends_with':
            return field_value.endswith(pattern)
        else:
            # Unknown operator
            return False

    def _extract_field(self, field: str, tool_name: str,
                      tool_input: Dict[str, Any], input_data: Dict[str, Any] = None) -> Optional[str]:
        """Extract field value from tool input or hook input data.

        Args:
            field: Field name like "command", "new_text", "file_path", "reason", "transcript"
            tool_name: Tool being used (may be empty for Stop events)
            tool_input: Tool input dict
            input_data: Full hook input (for accessing transcript_path, reason, etc.)

        Returns:
            Field value as string, or None if not found
        """
        # Direct tool_input fields
        if field in tool_input:
            value = tool_input[field]
            if isinstance(value, str):
                return value
            return str(value)

        # For Stop events and other non-tool events, check input_data
        if input_data:
            # Stop event specific fields
            if field == 'reason':
                return input_data.get('reason', '')
            elif field == 'transcript':
                # Read transcript file if path provided
                transcript_path = input_data.get('transcript_path')
                if transcript_path:
                    try:
                        with open(transcript_path, 'r', encoding='utf-8') as f:
                            return f.read()
                    except FileNotFoundError:
                        print(f"Warning: Transcript file not found: {transcript_path}", file=sys.stderr)
                        return ''
                    except PermissionError:
                        print(f"Warning: Permission denied reading transcript: {transcript_path}", file=sys.stderr)
                        return ''
                    except (IOError, OSError) as e:
                        print(f"Warning: Error reading transcript {transcript_path}: {e}", file=sys.stderr)
                        return ''
                    except UnicodeDecodeError as e:
                        print(f"Warning: Encoding error in transcript {transcript_path}: {e}", file=sys.stderr)
                        return ''
            elif field == 'user_prompt':
                # For UserPromptSubmit events
                return input_data.get('user_prompt', '')

        # Handle special cases by tool type
        if tool_name == 'Bash':
            if field == 'command':
                return tool_input.get('command', '')

        elif tool_name in ['Write', 'Edit']:
            if field == 'content':
                # Write uses 'content', Edit has 'new_string'
                return tool_input.get('content') or tool_input.get('new_string', '')
            elif field == 'new_text' or field == 'new_string':
                return tool_input.get('new_string', '')
            elif field == 'old_text' or field == 'old_string':
                return tool_input.get('old_string', '')
            elif field == 'file_path':
                return tool_input.get('file_path', '')

        elif tool_name == 'MultiEdit':
            if field == 'file_path':
                return tool_input.get('file_path', '')
            elif field in ['new_text', 'content']:
                # Concatenate all edits
                edits = tool_input.get('edits', [])
                return ' '.join(e.get('new_string', '') for e in edits)

        elif tool_name in ['Read', 'LS', 'Glob', 'Grep']:
            # 읽기 전용 도구: 경로만 추출. Glob/Grep의 pattern은 파일 경로로 보지 않는다.
            if field == 'file_path':
                if tool_name == 'Read':
                    return tool_input.get('file_path')
                elif tool_name == 'LS':
                    return tool_input.get('path')
                else:
                    return tool_input.get('path')

        return None

    def _regex_match(self, pattern: str, text: str) -> bool:
        """Check if pattern matches text using regex.

        Args:
            pattern: Regex pattern
            text: Text to match against

        Returns:
            True if pattern matches
        """
        try:
            # Use cached compiled regex (LRU cache with max 128 patterns)
            regex = compile_regex(pattern)
            return bool(regex.search(text))

        except re.error as e:
            print(f"Invalid regex pattern '{pattern}': {e}", file=sys.stderr)
            return False


# For testing
if __name__ == '__main__':
    from core.config_loader import Condition, Rule

    # Test rule evaluation
    rule = Rule(
        name="test-rm",
        enabled=True,
        event="bash",
        conditions=[
            Condition(field="command", operator="regex_match", pattern=r"rm\s+-rf")
        ],
        message="Dangerous rm command!"
    )

    engine = RuleEngine()

    # Test matching input
    test_input = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "rm -rf /tmp/test"
        }
    }

    result = engine.evaluate_rules([rule], test_input)
    print("Match result:", result)

    # Test non-matching input
    test_input2 = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "ls -la"
        }
    }

    result2 = engine.evaluate_rules([rule], test_input2)
    print("Non-match result:", result2)
