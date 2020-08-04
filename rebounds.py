#!/usr/bin/env python3

import attr
import functools
from collections import defaultdict
from parsy import alt, generate, string, any_char, char_from, test_char
import sys


# interesting bits:
#  - it's tough to handle anything that relies on locale or collation order,
#    so i haven't tried to deal with [:alnum:] and friends. if it's possible
#    to get the locale to tell you the smallest/largest member of each of those
#    sets, rather than just giving you a predicate, then it's easy. but i'm not
#    sure if such a thing exists.
#  - it's tough to be sure how to handle /./. currently any character is
#    fine there, from null on up to... the maximum unicode codepoint? does it
#    depend on locale?
#  - dealing with ^ and $ is tricky... (TODO explain why). currently they're
#    implicit anyway.
#  - i never tried to parse regex character classes before. they're so gnarly!

CHAR_MIN = chr(0)
CHAR_MAX = chr(0x10FFFF)


@attr.s
class Alt:
    terms = attr.ib()

    def to_nfa(self):
        assert self.terms
        n = Node()
        out_nodes = []
        for f in (t.to_nfa() for t in self.terms):
            n.eps_transitions.append(f.in_node)
            out_nodes += f.out_nodes
        return NfaFragment(n, out_nodes)


@attr.s
class Cat:
    factors = attr.ib()

    def to_nfa(self):
        def paste(l, r):
            for node in l.out_nodes:
                node.eps_transitions.append(r.in_node)
            return NfaFragment(l.in_node, r.out_nodes)

        if self.factors:
            return functools.reduce(paste, (f.to_nfa() for f in self.factors))
        else:
            n = Node()
            return NfaFragment(n, [n])


@attr.s
class Factor:
    base = attr.ib()
    rep = attr.ib()

    def to_nfa(self):
        base_frag = self.base.to_nfa()
        if self.rep == "?":
            n = Node()
            n.eps_transitions.append(base_frag.in_node)
            return NfaFragment(n, base_frag.out_nodes + [n])
        elif self.rep == "*":
            n = Node()
            n.eps_transitions.append(base_frag.in_node)
            for node in base_frag.out_nodes:
                node.eps_transitions.append(n)
            return NfaFragment(n, [n])
        elif self.rep == "+":
            n = Node()
            for node in base_frag.out_nodes:
                node.eps_transitions.append(n)
            n.eps_transitions.append(base_frag.in_node)
            return NfaFragment(base_frag.in_node, [n])
        assert self.rep is None
        return base_frag


@attr.s
class Lit:
    min = attr.ib()
    max = attr.ib()

    def to_nfa(self):
        fst = Node()
        snd = Node()
        fst.matcher = self
        fst.next = snd
        return NfaFragment(fst, [snd])


@generate
def factor():
    b = yield base
    rep = yield char_from("*?+").optional()
    return Factor(b, rep)


term = factor.many().map(Cat)
regex = term.sep_by(string("|"), min=1).map(Alt)


@attr.s
class PosIntervalBuilder:
    min = attr.ib(default=CHAR_MAX)
    max = attr.ib(default=CHAR_MIN)

    def add(self, start, end=None):
        if end is None:
            end = start
        self.min = min(self.min, start)
        self.max = max(self.max, end)


class NegIntervalBuilder:
    def __init__(self):
        self.endpoints = defaultdict(int)
        self.endpoints[CHAR_MIN] = 0
        self.endpoints[CHAR_MAX] = 0

    def add(self, start, end=None):
        if end is None:
            end = start
        self.endpoints[start] += 1
        self.endpoints[end] -= 1

    def get_first_zero(self, from_end=False):
        tally = 0
        for char, count in sorted(self.endpoints.items(), reverse=from_end):
            tally += count
            if tally == 0:
                return char
        assert False

    @property
    def min(self):
        return self.get_first_zero()

    @property
    def max(self):
        return self.get_first_zero(True)


@generate
def char_class():
    neg = yield string("[") >> string("^").optional()

    builder = NegIntervalBuilder() if neg else PosIntervalBuilder()
    first = True
    start = yield any_char
    while True:
        if start == "]" and not first:
            break
        first = False
        poss_range = yield any_char
        if poss_range != "-":
            # add start as standalone char
            builder.add(start)
            start = poss_range
            continue

        end = yield any_char
        if end == "]":
            # not a real range, the - is the last char in the class
            builder.add(start)
            builder.add(poss_range)
            break

        if end < start:
            raise RuntimeError(f"Invalid range: {start}-{end}")
        builder.add(start, end)
        start = yield any_char

    return Lit(builder.min, builder.max)


base = alt(
    char_from(".").result(Lit(CHAR_MIN, CHAR_MAX)),
    char_from("^$"),  # TODO
    string("\\") >> any_char.map(lambda c: Lit(c, c)),
    char_class,
    string("(") >> regex << string(")"),
    test_char(lambda c: c not in "?+*[()|", "").map(lambda c: Lit(c, c)),
)


@attr.s(eq=False)
class Node:
    eps_transitions = attr.ib(factory=list)
    matcher = attr.ib(default=None)
    next = attr.ib(default=None)

    def min_matching(self):
        return self.matcher.min

    def max_matching(self):
        return self.matcher.max


@attr.s
class NfaFragment:
    in_node = attr.ib()
    out_nodes = attr.ib()


class Nfa:
    def __init__(self, fragment):
        self.start = fragment.in_node
        self.end = Node()
        for n in fragment.out_nodes:
            n.eps_transitions.append(self.end)

    def __str__(self):
        return str(self.start)


def lower_bounds(bound, nfa):
    def insert(nodes, node):
        accepted = False
        if node == nfa.end:
            accepted = True
        if node.matcher:
            nodes.add(node)
        for n in node.eps_transitions:
            accepted |= insert(nodes, n)
        return accepted

    cur_nodes = set()
    insert(cur_nodes, nfa.start)
    for c in bound:
        next_nodes = set()
        for node in cur_nodes:
            if c < node.min_matching():
                continue
            if c > node.min_matching():
                return False
            if c == node.min_matching():
                if insert(next_nodes, node.next):
                    # we accepted the bound, or a prefix of the bound
                    return False
        if not next_nodes:
            return True
        cur_nodes = next_nodes

    return True


def upper_bounds(bound, nfa):
    def insert(nodes, node):
        accepted = False
        if node == nfa.end:
            accepted = True
        if node.matcher:
            nodes.add(node)
        for n in node.eps_transitions:
            accepted |= insert(nodes, n)
        return accepted

    cur_nodes = set()
    insert(cur_nodes, nfa.start)
    for c in bound:
        accepted = False
        if not cur_nodes:
            break
        next_nodes = set()
        for node in cur_nodes:
            if c > node.max_matching():
                continue
            if c < node.max_matching():
                return False
            if c == node.max_matching():
                accepted = insert(next_nodes, node.next)
        cur_nodes = next_nodes

    if accepted or cur_nodes:
        # we accepted the entire bound, or we exhausted it and can add a suffix
        return False
    return True


if __name__ == "__main__":
    bound = sys.argv[1]
    ast = regex.parse(sys.argv[2])
    nfa = Nfa(ast.to_nfa())
    print("lower: ", lower_bounds(bound, nfa))
    print("upper: ", upper_bounds(bound, nfa))
