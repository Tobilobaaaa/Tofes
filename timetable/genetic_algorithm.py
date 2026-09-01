"""
Genetic algorithm for a secondary-school timetable.

No halls/rooms: classes stay put and teachers move.
A chromosome is a list of teaching-slot indices — one gene per lesson session
(or elective block such as CHEM/COM/CRS, which share the same period).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any

from deap import base, creator, tools


HARD_WEIGHT = 1000
SOFT_WEIGHT = 8


@dataclass
class LessonPart:
    assignment_id: int
    class_id: int
    subject_id: int
    teacher_id: int
    option_group: str
    subject_code: str = ''


@dataclass
class SessionSpec:
    parts: list[LessonPart]
    session_index: int
    locked_slot_idx: int | None = None

    @property
    def class_ids(self) -> set[int]:
        return {p.class_id for p in self.parts}

    @property
    def teacher_ids(self) -> set[int]:
        return {p.teacher_id for p in self.parts}

    @property
    def subject_ids(self) -> set[int]:
        return {p.subject_id for p in self.parts}


@dataclass
class GAResult:
    best_chromosome: list[int]
    best_fitness: float
    hard_violations: int
    soft_violations: int
    generations: int
    execution_seconds: float
    fitness_history: list[float] = field(default_factory=list)
    success: bool = False
    message: str = ''


class SchoolTimetableGA:
    """Clash-free school timetable: teacher and class cannot be double-booked."""

    def __init__(
        self,
        sessions: list[SessionSpec],
        timeslots: list[dict[str, Any]],
        preferred_slots: dict[int, set[int]] | None = None,
        unavailable_slots: dict[int, set[int]] | None = None,
        population_size: int = 36,
        max_generations: int = 40,
        crossover_prob: float = 0.7,
        mutation_prob: float = 0.25,
        tournament_size: int = 3,
        seed: int | None = None,
        class_ids: list[int] | None = None,
        min_periods_weekday: int = 6,
        friday_periods: int = 5,
        subject_allowed_slots: dict[str, set[int]] | None = None,
    ):
        self.sessions = sessions
        self.timeslots = timeslots
        self.preferred_slots = preferred_slots or {}
        self.unavailable_slots = unavailable_slots or {}
        self.subject_allowed_slots = subject_allowed_slots or {}
        self.population_size = population_size
        self.max_generations = max_generations
        self.crossover_prob = crossover_prob
        self.mutation_prob = mutation_prob
        self.tournament_size = tournament_size
        self.class_ids = class_ids or sorted(
            {p.class_id for s in sessions for p in s.parts}
        )
        self.min_periods_weekday = min_periods_weekday
        self.friday_periods = friday_periods

        if seed is not None:
            random.seed(seed)

        self.n_slots = len(timeslots)
        self.n_sessions = len(sessions)
        self.teachable_indices = [
            i
            for i, ts in enumerate(timeslots)
            if not ts.get('is_break') and not ts.get('is_reserved')
        ]
        self.slot_day = [ts['day'] for ts in timeslots]
        self.slot_period = [ts['period'] for ts in timeslots]
        self.slot_is_break = [bool(ts.get('is_break')) for ts in timeslots]
        self.slot_is_reserved = [bool(ts.get('is_reserved')) for ts in timeslots]
        self.reserved_credit: dict[str, int] = {}
        for ts in timeslots:
            if ts.get('is_reserved'):
                self.reserved_credit[ts['day']] = self.reserved_credit.get(ts['day'], 0) + 1

        self._setup_deap()

    def _setup_deap(self):
        if hasattr(creator, 'FitnessMax'):
            del creator.FitnessMax
        if hasattr(creator, 'Individual'):
            del creator.Individual

        creator.create('FitnessMax', base.Fitness, weights=(1.0,))
        creator.create('Individual', list, fitness=creator.FitnessMax)

        self.toolbox = base.Toolbox()
        self.toolbox.register('individual', self._init_individual)
        self.toolbox.register('population', tools.initRepeat, list, self.toolbox.individual)
        self.toolbox.register('evaluate', self._evaluate)
        self.toolbox.register('mate', self._crossover)
        self.toolbox.register('mutate', self._mutate)
        self.toolbox.register('select', tools.selTournament, tournsize=self.tournament_size)

    def _constructive_genes(self) -> list[int]:
        """Place busiest teachers first; never double-book if a free slot exists."""
        demand: dict[int, int] = {}
        for session in self.sessions:
            for tid in session.teacher_ids:
                demand[tid] = demand.get(tid, 0) + 1
        order = list(range(self.n_sessions))
        random.shuffle(order)
        order.sort(
            key=lambda i: -max(
                (demand.get(t, 0) for t in self.sessions[i].teacher_ids),
                default=0,
            )
        )
        teacher_used: set[tuple[int, int]] = set()
        class_used: set[tuple[int, int]] = set()
        fallback = self.teachable_indices[0] if self.teachable_indices else 0
        genes = [fallback] * self.n_sessions
        leftover = []
        placed_by_subject: dict[tuple[int, int], list[int]] = {}

        def occupy(i, slot):
            genes[i] = slot
            for part in self.sessions[i].parts:
                teacher_used.add((part.teacher_id, slot))
                class_used.add((part.class_id, slot))
                placed_by_subject.setdefault(
                    (part.class_id, part.subject_id), []
                ).append(slot)

        def is_adjacent(session, slot):
            for part in session.parts:
                for prev in placed_by_subject.get((part.class_id, part.subject_id), []):
                    if (
                        self.slot_day[prev] == self.slot_day[slot]
                        and abs(self.slot_period[prev] - self.slot_period[slot]) == 1
                    ):
                        return True
            return False

        for i in order:
            session = self.sessions[i]
            if session.locked_slot_idx is not None:
                occupy(i, session.locked_slot_idx)
                continue
            chosen = None
            slots = list(self._open_slots(session))
            random.shuffle(slots)
            adjacent = []
            free = []
            for slot in slots:
                if self.slot_is_break[slot] or self.slot_is_reserved[slot]:
                    continue
                if any((tid, slot) in teacher_used for tid in session.teacher_ids):
                    continue
                if any((cid, slot) in class_used for cid in session.class_ids):
                    continue
                if is_adjacent(session, slot):
                    adjacent.append(slot)
                else:
                    free.append(slot)
            if adjacent:
                chosen = adjacent[0]
            elif free:
                chosen = free[0]
            if chosen is None:
                leftover.append(i)
            else:
                occupy(i, chosen)

        for i in leftover:
            session = self.sessions[i]
            slots = list(self._open_slots(session))
            random.shuffle(slots)
            chosen = None
            for slot in slots:
                if self.slot_is_break[slot] or self.slot_is_reserved[slot]:
                    continue
                if any((tid, slot) in teacher_used for tid in session.teacher_ids):
                    continue
                if any((cid, slot) in class_used for cid in session.class_ids):
                    continue
                chosen = slot
                break
            occupy(i, chosen if chosen is not None else (slots[0] if slots else fallback))
        return genes

    def _random_teachable(self) -> int:
        if not self.teachable_indices:
            return 0
        return random.choice(self.teachable_indices)

    def _subject_allowed(self, session: SessionSpec) -> set[int] | None:
        allowed: set[int] | None = None
        for part in session.parts:
            part_allowed = self.subject_allowed_slots.get(part.subject_code)
            if part_allowed is not None:
                allowed = part_allowed if allowed is None else allowed & part_allowed
        return allowed

    def _open_slots(self, session: SessionSpec) -> list[int]:
        slots = list(self.teachable_indices)
        blocked: set[int] = set()
        for teacher_id in session.teacher_ids:
            blocked |= self.unavailable_slots.get(teacher_id, set())
        if blocked:
            filtered = [s for s in slots if s not in blocked]
            if filtered:
                slots = filtered
        allowed = self._subject_allowed(session)
        if allowed is not None:
            filtered = [s for s in slots if s in allowed]
            if filtered:
                slots = filtered
        return slots or list(self.teachable_indices) or list(range(max(self.n_slots, 1)))

    def _candidate_slots(self, session: SessionSpec) -> list[int]:
        slots = self._open_slots(session)
        preferred: set[int] = set()
        for teacher_id in session.teacher_ids:
            preferred |= self.preferred_slots.get(teacher_id, set())
        if preferred:
            preferred_ok = [s for s in slots if s in preferred]
            if preferred_ok and random.random() < 0.45:
                return preferred_ok
        return slots

    def _init_individual(self):
        ind = creator.Individual()
        ind.extend(self._constructive_genes())
        return ind

    def _evaluate(self, individual: list[int]) -> tuple[float]:
        hard, soft = self._count_violations(individual)
        return (-(hard * HARD_WEIGHT + soft * SOFT_WEIGHT),)

    def _count_violations(self, individual: list[int]) -> tuple[int, int]:
        hard = 0
        soft = 0
        teacher_slots: dict[tuple[int, int], int] = {}
        class_slots: dict[tuple[int, int], int] = {}
        class_day_subjects: dict[tuple[int, str, int], list[int]] = {}
        class_day_periods: dict[tuple[int, str], list[int]] = {}
        teacher_day_periods: dict[tuple[int, str], list[int]] = {}

        for i, slot_idx in enumerate(individual):
            session = self.sessions[i]
            if slot_idx < 0 or slot_idx >= self.n_slots:
                hard += 1
                continue
            if self.slot_is_break[slot_idx] or self.slot_is_reserved[slot_idx]:
                hard += 1
            day = self.slot_day[slot_idx]
            period = self.slot_period[slot_idx]

            for part in session.parts:
                tk = (part.teacher_id, slot_idx)
                if tk in teacher_slots:
                    hard += 1
                else:
                    teacher_slots[tk] = i

                ck = (part.class_id, slot_idx)
                if ck in class_slots:
                    other = class_slots[ck]
                    other_groups = {
                        p.option_group
                        for p in self.sessions[other].parts
                        if p.class_id == part.class_id
                    }
                    same_group = bool(part.option_group) and part.option_group in other_groups
                    if not same_group:
                        hard += 1
                else:
                    class_slots[ck] = i

                unavailable = self.unavailable_slots.get(part.teacher_id, set())
                if slot_idx in unavailable:
                    hard += 1

                preferred = self.preferred_slots.get(part.teacher_id, set())
                if preferred and slot_idx not in preferred:
                    soft += 1

                allowed = self.subject_allowed_slots.get(part.subject_code)
                if allowed is not None and slot_idx not in allowed:
                    hard += 1

                subj_key = (part.class_id, day, part.subject_id)
                class_day_subjects.setdefault(subj_key, []).append(period)
                class_day_periods.setdefault((part.class_id, day), []).append(period)
                teacher_day_periods.setdefault((part.teacher_id, day), []).append(period)

        for periods in class_day_subjects.values():
            if len(periods) < 2:
                continue
            ordered = sorted(periods)
            consecutive = any(
                ordered[i + 1] - ordered[i] == 1 for i in range(len(ordered) - 1)
            )
            if consecutive:
                continue
            soft += len(ordered) - 1

        for periods in class_day_periods.values():
            if len(periods) < 2:
                continue
            periods = sorted(set(periods))
            span = periods[-1] - periods[0] + 1
            gaps = span - len(periods)
            soft += gaps

        for periods in teacher_day_periods.values():
            if len(periods) < 2:
                continue
            periods = sorted(set(periods))
            span = periods[-1] - periods[0] + 1
            gaps = span - len(periods)
            if gaps > 2:
                soft += gaps - 2

        # 6–7 periods Mon–Thu is enough (Sport counts on Wednesday).
        weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday']
        for class_id in self.class_ids:
            for day in weekdays:
                occupied = len(set(class_day_periods.get((class_id, day), [])))
                occupied += self.reserved_credit.get(day, 0)
                if occupied < self.min_periods_weekday:
                    soft += (self.min_periods_weekday - occupied) * 4
            friday_used = len(set(class_day_periods.get((class_id, 'Friday'), [])))
            if friday_used == 0:
                soft += 4

        return hard, soft

    def _crossover(self, ind1, ind2):
        if self.n_sessions < 2:
            return ind1, ind2
        tools.cxTwoPoint(ind1, ind2)
        for i, session in enumerate(self.sessions):
            if session.locked_slot_idx is not None:
                ind1[i] = session.locked_slot_idx
                ind2[i] = session.locked_slot_idx
        return ind1, ind2

    def _mutate(self, individual, indpb: float = 0.18):
        for i, session in enumerate(self.sessions):
            if session.locked_slot_idx is not None:
                individual[i] = session.locked_slot_idx
                continue
            if random.random() < indpb:
                individual[i] = random.choice(self._candidate_slots(session))
        return (individual,)

    def _session_fits(self, session: SessionSpec, slot: int, teacher_used, class_used) -> bool:
        if slot < 0 or slot >= self.n_slots:
            return False
        if self.slot_is_break[slot] or self.slot_is_reserved[slot]:
            return False
        for part in session.parts:
            if (part.teacher_id, slot) in teacher_used:
                return False
            if slot in self.unavailable_slots.get(part.teacher_id, set()):
                return False
            occupied_group = class_used.get((part.class_id, slot))
            if occupied_group is not None:
                if not part.option_group or part.option_group != occupied_group:
                    return False
        return True

    def _occupancy_except(self, chrom: list[int], skip: set[int]):
        teacher_used: set[tuple[int, int]] = set()
        class_used: dict[tuple[int, int], str] = {}
        for i, slot in enumerate(chrom):
            if i in skip:
                continue
            if slot < 0 or slot >= self.n_slots:
                continue
            for part in self.sessions[i].parts:
                teacher_used.add((part.teacher_id, slot))
                class_used[(part.class_id, slot)] = part.option_group
        return teacher_used, class_used

    def _greedy_repair(self, individual: list[int]) -> list[int]:
        chrom = list(individual)
        for _ in range(3):
            moved = False
            order = list(range(self.n_sessions))
            random.shuffle(order)
            for i in order:
                session = self.sessions[i]
                if session.locked_slot_idx is not None:
                    continue
                teacher_used, class_used = self._occupancy_except(chrom, {i})
                if self._session_fits(session, chrom[i], teacher_used, class_used):
                    continue
                slots = list(self._open_slots(session))
                random.shuffle(slots)
                for slot in slots:
                    if self._session_fits(session, slot, teacher_used, class_used):
                        chrom[i] = slot
                        moved = True
                        break
            if not moved:
                break
        return chrom

    def _day_load(self, chrom: list[int], class_id: int, day: str) -> int:
        used = set()
        for i, slot_idx in enumerate(chrom):
            if self.slot_day[slot_idx] != day:
                continue
            if any(p.class_id == class_id for p in self.sessions[i].parts):
                used.add(slot_idx)
        return len(used) + self.reserved_credit.get(day, 0)

    def _min_for_day(self, day: str) -> int:
        if day == 'Friday':
            return self.friday_periods
        return self.min_periods_weekday

    def _needs_balance(self, chrom: list[int]) -> bool:
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday']
        for class_id in self.class_ids:
            for day in days:
                if self._day_load(chrom, class_id, day) < self._min_for_day(day):
                    return True
        return False

    def _balance_days(self, individual: list[int]) -> list[int]:
        """Move lessons from over-full days onto days that are below the minimum."""
        chrom = list(individual)
        if not self._needs_balance(chrom):
            return chrom
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        for _ in range(4):
            moved = False
            for class_id in self.class_ids:
                loads = {d: self._day_load(chrom, class_id, d) for d in days}
                short = [d for d in days if loads[d] < self._min_for_day(d)]
                extra = [d for d in days if loads[d] > self._min_for_day(d)]
                if not short or not extra:
                    continue
                for s_idx, session in enumerate(self.sessions):
                    if session.locked_slot_idx is not None:
                        continue
                    if class_id not in session.class_ids:
                        continue
                    from_day = self.slot_day[chrom[s_idx]]
                    if from_day not in extra:
                        continue
                    teacher_used, class_used = self._occupancy_except(chrom, {s_idx})
                    candidates = [
                        i
                        for i in self._open_slots(session)
                        if self.slot_day[i] in short
                        and self._session_fits(session, i, teacher_used, class_used)
                    ]
                    if not candidates:
                        continue
                    chrom[s_idx] = random.choice(candidates)
                    moved = True
                    break
            if not moved:
                break
        return chrom

    def run(self) -> GAResult:
        if self.n_sessions == 0:
            return GAResult(
                best_chromosome=[],
                best_fitness=0,
                hard_violations=0,
                soft_violations=0,
                generations=0,
                execution_seconds=0,
                success=False,
                message='No lessons to schedule. Assign teachers to class subjects first.',
            )
        if self.n_slots == 0 or not self.teachable_indices:
            return GAResult(
                best_chromosome=[],
                best_fitness=0,
                hard_violations=0,
                soft_violations=0,
                generations=0,
                execution_seconds=0,
                success=False,
                message='Add teaching time slots (not just breaks) before generating.',
            )

        start = time.perf_counter()
        population = self.toolbox.population(n=self.population_size)

        fitnesses = list(map(self.toolbox.evaluate, population))
        for ind, fit in zip(population, fitnesses):
            ind.fitness.values = fit

        best = tools.selBest(population, 1)[0]
        history = [best.fitness.values[0]]
        generations_run = 0
        hard, _ = self._count_violations(best)

        if hard > 0:
            for gen in range(1, self.max_generations + 1):
                generations_run = gen
                offspring = self.toolbox.select(population, len(population))
                offspring = list(map(self.toolbox.clone, offspring))

                for c1, c2 in zip(offspring[::2], offspring[1::2]):
                    if random.random() < self.crossover_prob:
                        self.toolbox.mate(c1, c2)
                        del c1.fitness.values
                        del c2.fitness.values

                for mutant in offspring:
                    if random.random() < self.mutation_prob:
                        self.toolbox.mutate(mutant)
                        del mutant.fitness.values

                invalid = [ind for ind in offspring if not ind.fitness.valid]
                fits = map(self.toolbox.evaluate, invalid)
                for ind, fit in zip(invalid, fits):
                    ind.fitness.values = fit

                population[:] = offspring
                best = tools.selBest(population, 1)[0]
                history.append(best.fitness.values[0])

                hard, _ = self._count_violations(best)
                if hard == 0:
                    break

        best_chrom = list(best)
        hard, soft = self._count_violations(best_chrom)
        if hard > 0:
            best_chrom = self._greedy_repair(best_chrom)
            hard, soft = self._count_violations(best_chrom)
        if hard == 0:
            best_chrom = self._balance_days(best_chrom)
            hard, soft = self._count_violations(best_chrom)

        fitness = -(hard * HARD_WEIGHT + soft * SOFT_WEIGHT)
        elapsed = time.perf_counter() - start

        return GAResult(
            best_chromosome=best_chrom,
            best_fitness=fitness,
            hard_violations=hard,
            soft_violations=soft,
            generations=generations_run,
            execution_seconds=round(elapsed, 3),
            fitness_history=history,
            success=hard == 0,
            message=(
                'Clash-free timetable found.'
                if hard == 0
                else f'Still has {hard} hard clash(es) and {soft} soft issue(s). Try more generations or add teachers.'
            ),
        )


def build_sessions(assignments, locked_by_key: dict[tuple[int, int, int], int] | None = None):
    """
    Expand class assignments into sessions.

    Assignments that share (class, option_group) become one concurrent block
    so CHEM/COM/CRS occupy the same period for that class.
    locked_by_key maps (class_id, subject_id, session_index) → slot index.
    """
    locked_by_key = locked_by_key or {}
    grouped: dict[tuple[int, int], list] = {}
    singles: list = []

    for assignment in assignments:
        group = assignment.subject.simultaneous_group
        if group:
            key = (assignment.school_class_id, group.id)
            grouped.setdefault(key, []).append(assignment)
        else:
            singles.append(assignment)

    sessions: list[SessionSpec] = []

    def _parts_from(items) -> list[LessonPart]:
        return [
            LessonPart(
                assignment_id=a.id,
                class_id=a.school_class_id,
                subject_id=a.subject_id,
                teacher_id=a.teacher_id,
                option_group=(
                    a.subject.simultaneous_group.name
                    if a.subject.simultaneous_group_id
                    else ''
                ),
                subject_code=a.subject.code,
            )
            for a in items
        ]

    def _lock_for(parts: list[LessonPart], session_index: int) -> int | None:
        for part in parts:
            key = (part.class_id, part.subject_id, session_index)
            if key in locked_by_key:
                return locked_by_key[key]
        return None

    for assignment in singles:
        parts = _parts_from([assignment])
        for s_idx in range(1, assignment.periods_per_week + 1):
            sessions.append(
                SessionSpec(
                    parts=parts,
                    session_index=s_idx,
                    locked_slot_idx=_lock_for(parts, s_idx),
                )
            )

    for items in grouped.values():
        max_periods = max(a.periods_per_week for a in items)
        for s_idx in range(1, max_periods + 1):
            present = [a for a in items if a.periods_per_week >= s_idx]
            if not present:
                continue
            parts = _parts_from(present)
            sessions.append(
                SessionSpec(
                    parts=parts,
                    session_index=s_idx,
                    locked_slot_idx=_lock_for(parts, s_idx),
                )
            )

    return sessions
