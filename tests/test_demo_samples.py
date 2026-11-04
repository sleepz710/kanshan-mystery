"""任务19修订样本的证据门槛、文件指纹与结局回归。"""

import hashlib
import itertools
import json
from pathlib import Path

import pytest
import yaml

from backend.engine import GameEngine
from backend.studio.check import check_playability, check_structure


SAMPLES = Path(__file__).resolve().parents[1] / 'docs/testing/task19-demo'
ENTRIES = json.loads((SAMPLES / 'manifest.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('entry', ENTRIES, ids=lambda entry: entry['name'])
def test_sample_files_match_recorded_fingerprints(entry):
    for kind in ('original', 'revised'):
        path = SAMPLES / entry[f'{kind}_file']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry[f'{kind}_sha256']
    story = yaml.safe_load((SAMPLES / entry['revised_file']).read_text(encoding='utf-8'))
    assert story['checked'] is entry['checked']
    assert story['source'] == 'generated'
    assert check_structure(story) == {'ok': True, 'problems': []}
    assert check_playability(story) == []


@pytest.mark.parametrize('entry', ENTRIES, ids=lambda entry: entry['name'])
def test_final_revelations_are_locked_at_opening(entry, tmp_path):
    engine = GameEngine(stories_dir=tmp_path, generated_stories_dir=SAMPLES / 'revised')
    game = engine.new_game(entry['revised_id'])
    state = engine.games[game['game_id']]
    protected = {
        'hotel': {'f_seven_guests', 'f_zhouning_case', 'f_lin_coverup', 'f_zhouning_lost'},
        'tide': {'f_register', 'f_core'},
        'bus': {'f_douban', 'f_liangsu', 'f_su_open'},
    }[entry['name']]
    for character in game['characters']:
        allowed = {fact['id'] for fact in engine._context(state, character['id'], '')['facts']}
        assert not allowed & protected


@pytest.mark.parametrize('entry', ENTRIES, ids=lambda entry: entry['name'])
def test_wrong_answers_cannot_enter_complete_ending(entry):
    story = yaml.safe_load((SAMPLES / entry['revised_file']).read_text(encoding='utf-8'))
    questions = story['ending']['questions']
    complete = next(ending for ending in story['ending']['endings'] if not ending['retry'])
    complete_count = 0
    for options in itertools.product(*(question['options'] for question in questions)):
        answers = dict(zip((question['id'] for question in questions), options))
        results = {question['id']: answers[question['id']] == question['answer'] for question in questions}
        ending = next(ending for ending in story['ending']['endings']
                      if GameEngine._ending_matches(ending, answers, results))
        if ending['id'] == complete['id']:
            complete_count += 1
            assert all(results.values())
    assert complete_count == 1
