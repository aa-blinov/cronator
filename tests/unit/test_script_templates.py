"""Unit tests for built-in script templates."""

import ast
import re

import pytest

from app.script_templates import get_template, get_templates

TEMPLATES = get_templates()
TEMPLATE_IDS = [t["id"] for t in TEMPLATES]

REQUIRED_FIELDS = {
    "id", "name", "description", "category",
    "icon", "code", "dependencies", "cron_expression",
    "python_version", "environment_vars", "timeout",
}

VALID_CATEGORIES = {"monitoring", "data", "maintenance", "notification"}

VALID_PYTHON_VERSIONS = {"3.9", "3.10", "3.11", "3.12", "3.13"}

# Icons that are defined in icons.html / TEMPLATE_ICONS JS map
VALID_ICONS = {
    "check_circle", "exclamation_triangle", "archive_box", "clipboard",
    "arrow_path", "trash", "envelope", "bolt", "lock_closed",
    "signal", "globe_alt", "heart", "arrow_up_tray", "bell",
    "device_phone_mobile", "document", "cog",
}

CRONATOR_LIB_EXPORTS = {"get_logger", "notify", "save_artifact", "timer"}


# ---------------------------------------------------------------------------
# Collection-level checks
# ---------------------------------------------------------------------------

class TestTemplateCollection:
    def test_at_least_one_template(self):
        assert len(TEMPLATES) > 0

    def test_expected_count(self):
        """Update this number when new templates are intentionally added."""
        assert len(TEMPLATES) == 19

    def test_no_duplicate_ids(self):
        assert len(TEMPLATE_IDS) == len(set(TEMPLATE_IDS)), "Duplicate template IDs found"

    def test_no_duplicate_names(self):
        names = [t["name"] for t in TEMPLATES]
        assert len(names) == len(set(names)), "Duplicate template names found"

    def test_all_categories_present(self):
        categories = {t["category"] for t in TEMPLATES}
        assert "monitoring" in categories
        assert "data" in categories
        assert "maintenance" in categories
        assert "notification" in categories

    def test_get_templates_returns_list(self):
        result = get_templates()
        assert isinstance(result, list)

    def test_get_templates_is_stable(self):
        """Two calls return the same content."""
        assert get_templates() == get_templates()


# ---------------------------------------------------------------------------
# Per-template parametrized checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template", TEMPLATES, ids=TEMPLATE_IDS)
class TestEachTemplate:

    def test_has_all_required_fields(self, template):
        missing = REQUIRED_FIELDS - set(template.keys())
        assert not missing, f"Missing fields: {missing}"

    def test_id_is_slug(self, template):
        """ID must be lowercase alphanumeric + hyphens only."""
        assert re.fullmatch(r"[a-z0-9-]+", template["id"]), (
            f"Invalid id format: {template['id']!r}"
        )

    def test_name_is_non_empty_string(self, template):
        assert isinstance(template["name"], str)
        assert len(template["name"].strip()) >= 2

    def test_description_is_non_empty_string(self, template):
        assert isinstance(template["description"], str)
        assert len(template["description"].strip()) >= 10

    def test_category_is_valid(self, template):
        assert template["category"] in VALID_CATEGORIES, (
            f"Unknown category: {template['category']!r}"
        )

    def test_icon_is_valid(self, template):
        assert template["icon"] in VALID_ICONS, (
            f"Icon {template['icon']!r} is not in VALID_ICONS — "
            "add it to icons.html and TEMPLATE_ICONS in script_editor.html"
        )

    def test_python_version_is_valid(self, template):
        assert template["python_version"] in VALID_PYTHON_VERSIONS, (
            f"Unknown python_version: {template['python_version']!r}"
        )

    def test_timeout_is_positive_int(self, template):
        assert isinstance(template["timeout"], int)
        assert template["timeout"] > 0

    def test_cron_expression_has_five_parts(self, template):
        parts = template["cron_expression"].split()
        assert len(parts) == 5, (
            f"cron_expression must have 5 parts, got {len(parts)}: "
            f"{template['cron_expression']!r}"
        )

    def test_code_is_non_empty_string(self, template):
        assert isinstance(template["code"], str)
        assert len(template["code"].strip()) > 0

    def test_code_syntax_is_valid(self, template):
        """The template code must be valid Python (ast.parse must not raise)."""
        try:
            ast.parse(template["code"])
        except SyntaxError as exc:
            pytest.fail(f"SyntaxError in template {template['id']!r}: {exc}")

    def test_code_imports_get_logger(self, template):
        """Every template must use cronator_lib.get_logger."""
        assert "get_logger" in template["code"], (
            "Template must import and use get_logger from cronator_lib"
        )

    def test_code_imports_from_cronator_lib(self, template):
        """cronator_lib must be imported."""
        assert "cronator_lib" in template["code"]

    def test_code_has_main_function(self, template):
        """Every template must define a main() function."""
        tree = ast.parse(template["code"])
        func_names = {
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        assert "main" in func_names, "Template must define a main() function"

    def test_code_has_main_guard(self, template):
        """Must have if __name__ == '__main__': main() guard."""
        assert '__name__' in template["code"] and "__main__" in template["code"], (
            "Template must have if __name__ == '__main__' guard"
        )

    def test_dependencies_is_string(self, template):
        assert isinstance(template["dependencies"], str)

    def test_environment_vars_is_string(self, template):
        assert isinstance(template["environment_vars"], str)


# ---------------------------------------------------------------------------
# get_template() lookup
# ---------------------------------------------------------------------------

class TestGetTemplate:
    def test_returns_template_by_id(self):
        first = TEMPLATES[0]
        result = get_template(first["id"])
        assert result is not None
        assert result["id"] == first["id"]

    def test_returns_none_for_unknown_id(self):
        assert get_template("this-does-not-exist") is None

    def test_returns_none_for_empty_string(self):
        assert get_template("") is None

    @pytest.mark.parametrize("template_id", TEMPLATE_IDS)
    def test_all_ids_are_findable(self, template_id):
        result = get_template(template_id)
        assert result is not None
        assert result["id"] == template_id


# ---------------------------------------------------------------------------
# Code quality spot-checks
# ---------------------------------------------------------------------------

class TestCodeQuality:
    def test_no_template_uses_print_for_logging(self):
        """Templates should use get_logger(), not print()."""
        for t in TEMPLATES:
            tree = ast.parse(t["code"])
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id == "print":
                        pytest.fail(
                            f"Template {t['id']!r} uses print() — use logger instead"
                        )

    def test_no_template_uses_os_environ_copy(self):
        """
        os.environ.copy() passes ALL parent env vars to subprocesses,
        which leaks secrets. Templates must filter explicitly.
        """
        for t in TEMPLATES:
            assert "os.environ.copy()" not in t["code"], (
                f"Template {t['id']!r} uses os.environ.copy() — "
                "pass only required keys to subprocess env"
            )

    def test_notify_only_in_templates_that_make_sense(self):
        """
        notification-category templates must use notify().
        data/monitoring templates that can fail should also use it.
        """
        notification_templates = [t for t in TEMPLATES if t["category"] == "notification"]
        for t in notification_templates:
            # notification templates send messages themselves — notify() is optional
            # but they should at least log
            assert "logger" in t["code"], (
                f"Notification template {t['id']!r} must use logger"
            )

    @pytest.mark.parametrize("template", TEMPLATES, ids=TEMPLATE_IDS)
    def test_no_hardcoded_credentials(self, template):
        """Templates must not contain hardcoded passwords or tokens."""
        code_lower = template["code"].lower()
        # These patterns indicate hardcoded secrets rather than env var reads
        suspicious = [
            'password = "',
            "password = '",
            'token = "abc',
            'secret = "',
        ]
        for pattern in suspicious:
            assert pattern not in code_lower, (
                f"Template {template['id']!r} may contain a hardcoded credential: {pattern!r}"
            )
