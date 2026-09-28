import unittest
from harness import Arena, Planner


class HarnessTests(unittest.TestCase):
    def test_illegal_action_does_not_mutate_arena(self):
        game=Arena();before=game.observe()
        with self.assertRaises(ValueError):game.step('move:99')
        self.assertEqual(before,game.observe())

    def test_switch_pruning_prevents_equal_damage_cycle(self):
        game=Arena();p=Planner('local')
        self.assertTrue(all(not a['id'].startswith('switch:') for a in p.candidates(game.observe())))
        game.step('move:0');game.step('move:0')
        self.assertIn('switch:2',[a['id'] for a in p.candidates(game.observe())])

    def test_unfiltered_policy_exposes_every_legal_action(self):
        game=Arena();p=Planner('local',policy='unfiltered')
        observation=game.observe()
        self.assertEqual(observation['legal_actions'],p.candidates(observation))

    def test_knockout_avoids_retaliation(self):
        game=Arena();game.step('move:0');hp=game.team[0]['hp'];game.step('move:0')
        self.assertEqual(game.team[0]['hp'],hp)
        self.assertEqual(game.stage,1)

    def test_baseline_reaches_terminal_win_with_finite_budget(self):
        game=Arena();planner=Planner('rules')
        while game.status=='playing':game.step(planner.choose(game.observe())['action'])
        self.assertEqual(game.status,'won');self.assertLess(game.turn,40)

    def test_local_mode_rejects_nonlocal_endpoint(self):
        with self.assertRaises(ValueError):Planner('local','https://example.com/v1')

    def test_unknown_policy_is_rejected(self):
        with self.assertRaises(ValueError):Planner('rules',policy='unknown')


if __name__=='__main__':unittest.main()
