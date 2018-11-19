# -*- coding: utf-8 -*-
#
#  Copyright 2017, 2018 Ramil Nugmanov <stsouko@live.ru>
#  This file is part of CGRtools.
#
#  CGRtools is free software; you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, see <https://www.gnu.org/licenses/>.
#
from collections import defaultdict
from itertools import repeat, zip_longest
from .molecule import MoleculeContainer
from ..algorithms import AromatizeCGR, StereoCGR, StringCGR
from ..attributes import DynAtom, DynBond, DynamicContainer
from ..periodictable import H


class CGRContainer(StringCGR, StereoCGR, AromatizeCGR, MoleculeContainer):
    """
    storage for CGRs. has similar to molecules behavior
    """

    node_attr_dict_factory = DynAtom
    edge_attr_dict_factory = DynBond

    def get_center_atoms(self, stereo=False):
        """ get list of atoms of reaction center (atoms with dynamic: bonds, stereo, charges, radicals).
        """
        nodes = set()
        for n, atom in self.nodes(data=True):
            if atom.reagent != atom.product or stereo and atom.stereo != atom.p_stereo:
                nodes.add(n)

        for *n, bond in self.edges(data=True):
            if bond.reagent != bond.product or stereo and bond.stereo != bond.p_stereo:
                nodes.update(n)

        return list(nodes)

    def decompose(self):
        """
        decompose CGR to pair of Molecules, which represents reagents and products state of reaction

        :return: tuple of two molecules
        """
        reagents = MoleculeContainer()
        products = MoleculeContainer()

        reagents.add_nodes_from((n, atom.reagent) for n, atom in self.nodes(data=True))
        products.add_nodes_from((n, atom.product) for n, atom in self.nodes(data=True))
        nmb = list(self.edges(data=True))
        reagents.add_edges_from((n, m, bond.reagent) for n, m, bond in nmb if bond.order)
        products.add_edges_from((n, m, bond.product) for n, m, bond in nmb if bond.p_order)
        return DynamicContainer(reagents, products)

    def __invert__(self):
        """
        decompose CGR
        """
        return self.decompose()

    def reset_query_marks(self, copy=False):
        """
        set or reset hyb and neighbors marks to atoms.

        :param copy: if True return copy of graph and keep existing as is
        :return: graph if copy True else None
        """
        g = self.copy() if copy else self
        for i, atom in g._node.items():
            neighbors = 0
            hybridization = 1
            p_neighbors = 0
            p_hybridization = 1
            # hyb 1- sp3; 2- sp2; 3- sp1; 4- aromatic
            for j, bond in g._adj[i].items():
                isnth = g._node[j] != 'H'

                order = bond.order
                if order:
                    if isnth:
                        neighbors += 1
                    if hybridization not in (3, 4):
                        if order == 4:
                            hybridization = 4
                        elif order == 3:
                            hybridization = 3
                        elif order == 2:
                            if hybridization == 2:
                                hybridization = 3
                            else:
                                hybridization = 2
                order = bond.p_order
                if order:
                    if isnth:
                        p_neighbors += 1
                    if p_hybridization not in (3, 4):
                        if order == 4:
                            p_hybridization = 4
                        elif order == 3:
                            p_hybridization = 3
                        elif order == 2:
                            if p_hybridization == 2:
                                p_hybridization = 3
                            else:
                                p_hybridization = 2

            atom.neighbors = neighbors
            atom.hybridization = hybridization
            atom.p_neighbors = p_neighbors
            atom.p_hybridization = p_hybridization
        if copy:
            return g
        self.flush_cache()

    def implicify_hydrogens(self):
        """
        remove explicit hydrogens if possible

        :return: number of removed hydrogens
        """
        explicit = defaultdict(list)
        hydrogens = set()
        for_remove = []
        c = 0
        for n, attr in self.nodes(data='element'):
            if attr == 'H':
                for m in self.neighbors(n):
                    if self.nodes[m]['element'] != 'H':
                        explicit[m].append(n)
                    else:
                        hydrogens.add(m)
                        hydrogens.add(n)

        for n, h in explicit.items():
            s_atom, p_atom = self.atom(n)
            self_n = self[n]

            s_bonds = [y['s_bond'] for x, y in self_n.items() if x not in h and y.get('s_bond')]
            p_bonds = [y['p_bond'] for x, y in self_n.items() if x not in h and y.get('p_bond')]

            s_implicit = s_atom.get_implicit_h(s_bonds)
            p_implicit = p_atom.get_implicit_h(p_bonds)

            if not s_implicit and any(self_n[x].get('s_bond') for x in h):
                hydrogens.update(h)
            elif not p_implicit and any(self_n[x].get('p_bond') for x in h):
                hydrogens.update(h)
            else:
                for x in h:
                    for_remove.append(x)

        for x in for_remove:
            if x not in hydrogens:
                self.remove_node(x)
                c += 1

        self.flush_cache()
        return c

    def explicify_hydrogens(self):
        """
        add explicit hydrogens to atoms

        :return: number of added atoms
        """
        tmp = []
        for n, attr in self.nodes(data='element'):
            if attr != 'H':
                si, pi = self.atom_implicit_h(n)
                if si or pi:
                    for s_mark, p_mark in zip_longest(repeat(1, si), repeat(1, pi)):
                        tmp.append((n, s_mark, p_mark))

        for n, s_mark, p_mark in tmp:
            self.add_bond(n, self.add_atom(H()), s_mark, p_mark)

        self.flush_cache()
        return len(tmp)

    def atom_implicit_h(self, atom):
        atom = self._node[atom]
        ri = atom.reagent.get_implicit_h([x.order for x in self._adj[atom].values()])
        pi = atom.product.get_implicit_h([x.p_order for x in self._adj[atom].values()])
        return DynamicContainer(ri, pi)

    def atom_explicit_h(self, atom):
        rh = sum(self.nodes[x]['element'] == 'H' for x, a in self[atom].items() if a.get('s_bond'))
        ph = sum(self.nodes[x]['element'] == 'H' for x, a in self[atom].items() if a.get('p_bond'))
        return DynamicContainer(rh, ph)

    def atom_total_h(self, atom):
        rh, ph = self.atom_explicit_h(atom)
        ri, pi = self.atom_implicit_h(atom)
        return DynamicContainer(ri + rh, pi + ph)

    def check_valence(self):
        """
        check valences of all atoms

        :return: list of invalid atoms
        """
        report = []
        for x, atom in self._node.items():
            env = self.environment(x)
            if not atom.reagent.check_valence([(b.reagent, a.reagent) for b, a in env if b.order]) or \
                    not atom.product.check_valence([(b.product, a.product) for b, a in env if b.p_order]):
                report.append(f'atom {x} has invalid valence')
        return report

    _visible = ()
