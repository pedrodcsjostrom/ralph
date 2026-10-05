"""`ralph run <spec>`: an unattended run implements the frontier and closes tickets."""

import unittest

from tests.harness import ScenarioTestCase


class ImplementsTheFrontier(ScenarioTestCase):
    def test_tickets_are_implemented_in_frontier_order_and_closed(self):
        s = self.scenario()
        # 2 is blocked by 3, so 3 goes first although it has the higher number.
        s.ticket(2, blocked_by=[3])
        s.ticket(3)
        s.ticket(4)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #3", "close #3", "agent #2", "close #2", "agent #4", "close #4"])
        self.assertEqual(
            s.log("main..HEAD"),
            ["Implement ticket (#3)", "Implement ticket (#2)", "Implement ticket (#4)"],
        )
        for number in (2, 3, 4):
            self.assertEqual(s.issue(number)["state"], "closed")

    def test_unready_and_blocked_tickets_are_not_picked(self):
        s = self.scenario()
        s.ticket(2, labels=["ready-for-human"])
        s.ticket(3, blocked_by=[2])
        s.ticket(4, labels=[])
        s.ticket(5)

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 1, result.output)
        self.assertEqual(s.events(), ["agent #5", "close #5"])
        self.assertIn("nothing on the frontier can be implemented", result.output)
        self.assertIn("#2 Ticket 2\n#3 Ticket 3\n#4 Ticket 4\n", result.output)
        self.assertNotIn("#5 Ticket 5", result.output)

    def test_a_ticket_is_picked_once_its_blocker_is_closed(self):
        s = self.scenario()
        s.ticket(2, blocked_by=[4])
        s.ticket(3, blocked_by=[9], state="open")
        s.ticket(4)
        s.ticket(9, state="closed")

        result = s.ralph("run", "1")

        self.assertEqual(result.status, 0, result.output)
        self.assertEqual(s.events(), ["agent #3", "close #3", "agent #4", "close #4", "agent #2", "close #2"])


if __name__ == "__main__":
    unittest.main()
