import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tasks' / 'Component' / 'QuickLoadout' / 'quick_loadout.py'


def _load_pure_helpers():
    module = ast.parse(SOURCE.read_text(encoding='utf-8'))
    quick_loadout = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == 'QuickLoadout'
    )
    names = {'_parse_custom_presets', '_normalize_name', '_name_similarity', '_match_custom_preset'}
    methods = []
    for node in quick_loadout.body:
        if isinstance(node, ast.Assign):
            assigned = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if 'STAGE_NAME_MATCH_THRESHOLD' in assigned:
                methods.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            methods.append(node)
    isolated = ast.Module(
        body=[
            ast.Import(names=[ast.alias(name='ast')]),
            ast.Import(names=[ast.alias(name='difflib')]),
            ast.Import(names=[ast.alias(name='re')]),
            ast.ClassDef(
                name='QuickLoadout', bases=[], keywords=[], body=methods, decorator_list=[]
            ),
        ],
        type_ignores=[],
    )
    namespace = {}
    exec(compile(ast.fix_missing_locations(isolated), str(SOURCE), 'exec'), namespace)
    return namespace['QuickLoadout']


def test_custom_preset_parser_supports_multiple_entries():
    quick = _load_pure_helpers()
    assert quick._parse_custom_presets('ALL:(1,1);雷麒麟:(2,3)；') == {
        'ALL': ('1', '1'),
        '雷麒麟': ('2', '3'),
    }


def test_explicit_stage_has_priority_over_all():
    quick = _load_pure_helpers()
    presets = {'ALL': ('1', '1'), '雷麒麟': ('2', '3')}
    assert quick._match_custom_preset('雷 麒麟', presets)[:2] == (
        '雷麒麟', ('2', '3')
    )


def test_all_matches_stage_without_explicit_entry():
    quick = _load_pure_helpers()
    presets = {'ALL': ('1', '1'), '雷麒麟': ('2', '3')}
    assert quick._match_custom_preset('水麒麟', presets) == (
        'ALL', ('1', '1'), 1.0
    )
