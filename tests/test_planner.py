from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import app as backend
import planner


def bells():
    return {"shifts": {
        "1": {d: {"1": {"start": "08:00", "end": "08:40"}, "2": {"start": "09:00", "end": "09:40"}} for d in planner.DAYS},
        "2": {d: {"1": {"start": "08:20", "end": "09:00"}, "2": {"start": "10:00", "end": "10:40"}} for d in planner.DAYS},
    }}


def project():
    return planner.Project.model_validate({
        "classes": [{"name": "5а"}, {"name": "6а", "shift": 2}],
        "teachers": [{"name": "Учитель"}, {"name": "Другой"}],
        "subjects": [{"name": "Математика"}],
        "rooms": [{"name": "101"}, {"name": "102"}],
        "loads": [
            {"id": "a", "class_name": "5а", "teacher": "Учитель", "subject": "Математика", "room": "101", "per_week": 2},
            {"id": "b", "class_name": "6а", "teacher": "Учитель", "subject": "Математика", "room": "102", "per_week": 1},
        ],
    })


class PlannerTests(unittest.TestCase):
    def test_conflicts_use_real_times_across_shifts(self):
        p = project()
        p.placements = [planner.Placement(load_id="a", day="Пн", lesson=1), planner.Placement(load_id="b", day="Пн", lesson=1)]
        self.assertTrue(any("учитель" in issue for issue in planner.issues(p, bells())))
        p.placements[1].lesson = 2
        self.assertFalse(planner.issues(p, bells()))
        p.loads[1].room = "101"
        p.placements[1].lesson = 1
        self.assertTrue(any("кабинет" in issue for issue in planner.issues(p, bells())))

    def test_unavailable_applies_to_overlapping_shift(self):
        p = project()
        p.teachers[0].unavailable = [planner.Slot(day="Пн", shift=1, lesson=1)]
        p.placements = [planner.Placement(load_id="b", day="Пн", lesson=1)]
        self.assertTrue(any("недоступен" in issue for issue in planner.issues(p, bells())))
        self.assertTrue(any("нет звонков" in issue for issue in planner.issues(p, None)))

    def test_generate_preserves_manual_placements_and_validates(self):
        p = project()
        p.placements = [planner.Placement(load_id="a", day="Пн", lesson=1)]
        generated, error = planner.generate(p, bells())
        self.assertEqual(error, "")
        self.assertIsNotNone(generated)
        self.assertEqual(generated.placements[0], p.placements[0])
        self.assertEqual(len(p.placements), 1)
        self.assertEqual(planner.issues(generated, bells(), complete=True), [])
        teachers, subjects = planner.public_grids(generated)
        self.assertEqual(teachers["numbering"], "local")
        self.assertEqual(subjects["numbering"], "local")
        self.assertEqual(teachers["grid"]["Пн"]["1"]["5а"]["rooms"], ["101"])

    def test_daily_limits_and_missing_bells(self):
        p = project()
        p.classes[0].max_daily = 1
        p.placements = [planner.Placement(load_id="a", day="Пн", lesson=1), planner.Placement(load_id="a", day="Пн", lesson=2)]
        errors = planner.issues(p, bells())
        self.assertTrue(any("дневной предел уроков" in x for x in errors))
        self.assertTrue(any("дневной предел нагрузки" in x for x in errors))
        self.assertTrue(any("нет времени звонков" in x for x in planner.issues(p, None)))

    def test_failure_does_not_change_draft(self):
        p = project()
        before = p.model_dump()
        generated, error = planner.generate(p, None)
        self.assertIsNone(generated)
        self.assertTrue(error)
        self.assertEqual(before, p.model_dump())

    def test_reference_validation_and_incomplete(self):
        p = project()
        self.assertTrue(any("расставлено" in x for x in planner.issues(p, bells(), complete=True)))
        p.rooms = []
        self.assertTrue(any("кабинет" in x for x in planner.references(p)))

    def test_api_publish_and_revision_guard(self):
        original = copy.deepcopy(backend.state)
        try:
            backend.state["planner"] = None
            backend.state["bell_schedule"] = bells()
            with patch.object(backend, "_save_state"):
                p = project()
                saved = backend.planner_save(p)
                with self.assertRaises(backend.HTTPException) as conflict:
                    backend.planner_save(project())
                self.assertEqual(conflict.exception.status_code, 409)
                with self.assertRaises(backend.HTTPException):
                    backend.planner_publish(backend.PlannerAction(revision=saved["project"]["revision"]))
                generated = backend.planner_generate(backend.PlannerAction(revision=saved["project"]["revision"]))
                backend.planner_publish(backend.PlannerAction(revision=generated["project"]["revision"]))
                self.assertEqual(backend.state["second_shift_classes"], ["6а"])
                self.assertEqual(backend.state["subjects"]["numbering"], "local")
        finally:
            backend.state.clear()
            backend.state.update(original)


if __name__ == "__main__":
    unittest.main()
