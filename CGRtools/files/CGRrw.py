# -*- coding: utf-8 -*-
#
#  Copyright 2014-2017 Ramil Nugmanov <stsouko@live.ru>
#  This file is part of CGRtools.
#
#  CGRtools is free software; you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
from itertools import count, product, chain
from collections import defaultdict
from periodictable import elements
from ..containers import ReactionContainer, MoleculeContainer

toMDL = {-3: 7, -2: 6, -1: 5, 0: 0, 1: 3, 2: 2, 3: 1}
fromMDL = {0: 0, 1: 3, 2: 2, 3: 1, 4: 0, 5: -1, 6: -2, 7: -3}
bondlabels = {'0': None, '1': 1, '2': 2, '3': 3, '4': 4, '9': 9, 'n': None, 's': 9}
stereolabels = dict(e='e', z='z', u='u', r='r', s='s', re='re', si='si', n=None)
mendeleyset = set(x.symbol for x in elements)
half_table = len(mendeleyset) // 2


class EmptyMolecule(Exception):
    pass


class FinalizedFile(Exception):
    pass


class CGRread:
    def __init__(self, remap):
        self.__remap = remap
        self.__prop = {}

    def _collect(self, line):
        if line.startswith('M  ALS'):
            self.__prop[line[3:10]] = dict(atoms=[int(line[7:10])],
                                           type='atomlist' if line[14] == 'F' else 'atomnotlist',
                                           value=[line[16 + x*4: 20 + x*4].strip() for x in range(int(line[10:13]))])
        elif line.startswith('M  ISO'):
            self.__prop[line[3:10]] = dict(atoms=[int(line[10:13])], type='isotope', value=line[14:17].strip())

        elif line.startswith('M  STY'):
            for i in range(int(line[8])):
                if 'DAT' in line[10 + 8 * i:17 + 8 * i]:
                    self.__prop[int(line[10 + 8 * i:13 + 8 * i])] = {}
        elif line.startswith('M  SAL') and int(line[7:10]) in self.__prop:
            key = []
            for i in range(int(line[10:13])):
                key.append(int(line[14 + 4 * i:17 + 4 * i]))
            self.__prop[int(line[7:10])]['atoms'] = sorted(key)
        elif line.startswith('M  SDT') and int(line[7:10]) in self.__prop:
            key = line.split()[-1].lower()
            if key not in self.__cgrkeys:
                self.__prop.pop(int(line[7:10]))
            else:
                self.__prop[int(line[7:10])]['type'] = key
        elif line.startswith('M  SED') and int(line[7:10]) in self.__prop:
            self.__prop[int(line[7:10])]['value'] = line[10:].strip().replace('/', '').lower()

    def _flush_collected(self):
        self.__prop.clear()

    def _get_collected(self):
        prop = []
        for i in self.__prop.values():
            if len(i['atoms']) == self.__cgrkeys[i['type']]:
                prop.append(i)

        self.__prop.clear()
        return prop

    def _get_reaction(self, reaction):
        maps = {'substrats': [y['map'] for x in reaction['substrats'] for y in x['atoms']],
                'products': [y['map'] for x in reaction['products'] for y in x['atoms']]}
        length = count(max((max(maps['products'], default=0), max(maps['substrats'], default=0))) + 1)

        ''' map unmapped atoms
        '''
        for i in ('substrats', 'products'):
            if 0 in maps[i]:
                maps[i] = [j or next(length) for j in maps[i]]

            if len(maps[i]) != len(set(maps[i])):
                raise Exception("MapError")
        ''' end
        '''
        ''' find breaks in map. e.g. 1,2,5,6. 3,4 - skipped
        '''
        if self.__remap:
            lose = sorted(set(range(1, next(length))).difference(maps['products']).difference(maps['substrats']),
                          reverse=True)
            if lose:
                for k in ('substrats', 'products'):
                    for i in lose:
                        maps[k] = [j if j < i else j - 1 for j in maps[k]]
        ''' end
        '''
        rc = ReactionContainer(meta={x: '\n'.join(y) for x, y in reaction['meta'].items()})

        colors = defaultdict(dict)
        for k, v in reaction['colors'].items():
            color_type, mol_num = k.split('.')
            colors[int(mol_num)][color_type] = v

        counter = count(1)
        for i in ('substrats', 'products'):
            shift = 0
            for j in reaction[i]:
                atom_len = len(j['atoms'])
                remapped = {x: y for x, y in enumerate(maps[i][shift: atom_len + shift], start=1)}
                shift += atom_len
                g = self.__parse_molecule(j, remapped, colors=colors[next(counter)])
                rc[i].append(g)
        return rc

    def _get_molecule(self, molecule):
        length = count(max(x['map'] for x in molecule['atoms']) + 1)
        remapped = {k: (k if self.__remap else l['map'] or next(length))
                    for k, l in enumerate(molecule['atoms'], start=1)}
        return self.__parse_molecule(molecule, remapped, meta=molecule['meta'], colors=molecule['colors'])

    @classmethod
    def __parsedyn(cls, name, value):
        tmp0, tmp1 = [], []
        for x in value.split(','):
            s, *_, p = x.split('>')
            if s != p:
                tmp0.append(bondlabels[s] if name == 'bond' else
                            stereolabels[s] if name == 'stereo' else (s != 'n' and int(s) or None))
                tmp1.append(bondlabels[p] if name == 'bond' else
                            stereolabels[p] if name == 'stereo' else (p != 'n' and int(p) or None))

        s, p, sp = cls.__marks[name]
        if len(tmp0) == 1:
            out = {sp: (tmp0[0], tmp1[0])}
            if tmp0[0] is not None:
                out[s] = tmp0[0]
            if tmp1[0] is not None:
                out[p] = tmp1[0]
            return out
        elif len(tmp0) > 1:
            tmp2 = list(zip(tmp0, tmp1))
            if len(set(tmp2)) == len(tmp2):
                return {s: tmp0, p: tmp1, sp: tmp2}

    @classmethod
    def __parselist(cls, name, value):
        tmp = [bondlabels[x] if name == 'bond' else
               stereolabels[x] if name == 'stereo' else (x != 'n' and int(x) or None) for x in value.split(',')]

        if len(tmp) == 1:
            if tmp[0] is not None:
                return dict.fromkeys(cls.__marks[name], tmp[0])
        elif len(set(tmp)) == len(tmp):
            return dict.fromkeys(cls.__marks[name], tmp)

    @classmethod
    def __cgr_atom_dat(cls, value, charge):
        key = value[0]
        if key == 'c':  # update atom charges from CGR
            diff = [int(x) for x in value[1:].split(',')]
            if len(diff) > 1:
                if diff[0] == 0:  # for list of charges c0,1,-2,+3...
                    tmp = [charge + x for x in diff]
                    if len(set(tmp)) == len(tmp):
                        return dict(s_charge=tmp, p_charge=tmp, sp_charge=tmp)
                elif len(diff) % 2 == 1:  # for dyn charges c1,-1,0... -1,0 is dyn group relatively to base
                    s = [charge] + [charge + x for x in diff[1::2]]
                    p = [charge + x for x in diff[::2]]
                    tmp = list(zip(s, p))
                    if len(set(tmp)) == len(tmp):
                        return dict(s_charge=s, p_charge=p, sp_charge=tmp)
            else:
                tmp = diff[0]
                if tmp:
                    p = charge + tmp
                    return dict(s_charge=charge, p_charge=p, sp_charge=(charge, p))
        elif key == 'x':
            x, y, z = (float(x) for x in value[1:].split(','))
            return dict(p_x=x, p_y=y, p_z=z)
        elif key == 'z':
            return dict(dz=int(value[1:]))

    @classmethod
    def __cgr_dat(cls, _type, value):
        if _type == 'dynbond':
            return cls.__parsedyn('bond', value)

        elif _type == 'extrabond':
            return cls.__parselist('bond', value)

        elif _type == 'atomlist':
            return dict(element=value)

        elif _type == 'atomnotlist':
            return dict(element=list(mendeleyset.difference(value)))

        elif _type == 'atomhyb':
            return cls.__parselist('hyb', value)

        elif _type == 'atomneighbors':
            return cls.__parselist('neighbors', value)

        elif _type == 'dynatomhyb':
            return cls.__parsedyn('hyb', value)

        elif _type == 'dynatomneighbors':
            return cls.__parsedyn('neighbors', value)

        elif _type == 'isotope':
            tmp = value.split(',')
            return dict(isotope=[int(x) for x in tmp] if len(tmp) > 1 else int(tmp[0]))

    @staticmethod
    def __parse_colors(key, colors):
        adhoc, before, res = [], [], {}
        for x in colors:
            if (len(x) == 81 or len(x) == 75 and not before) and x[-1] == '+':
                before.append(x[:-1])
            else:
                before.append(x)
                adhoc.append(''.join(before))
                before = []

        for population, *keys in (x.split() for x in adhoc):
            for atom, val in (x.split(':') for x in keys):
                a = int(atom)
                p = int(population)
                if not key.startswith('dyn'):
                    res.setdefault(a, {}).setdefault('s_%s' % key, {})[p] = val
                    res[a].setdefault('p_%s' % key, {})[p] = val
                else:
                    v1, v2 = val.split('>')
                    res.setdefault(a, {}).setdefault('s_%s' % key[3:], {})[p] = v1
                    res[a].setdefault('p_%s' % key[3:], {})[p] = v2
        return res

    @classmethod
    def __parse_molecule(cls, molecule, mapping, meta=None, colors=None):
        g = MoleculeContainer(meta=meta and {x: '\n'.join(y) for x, y in meta.items()})
        mdl_s_stereo = mdl_p_stereo = True
        cgr_dat_atom = {}
        cgr_dat_bond = {}
        for k in molecule['CGR_DAT']:
            if k['type'] == 'dynatom':
                val = cls.__cgr_atom_dat(k['value'], molecule['atoms'][k['atoms'][0] - 1]['charge'])
                cgr_dat_atom.setdefault(k['atoms'][0], {}).update(val)
            else:
                val = cls.__cgr_dat(k['type'], k['value'])
                if val:
                    if cls.__cgrkeys[k['type']] == 2:
                        a1, a2 = k['atoms']
                        cgr_dat_bond.setdefault(a1, {})[a2] = val
                        cgr_dat_bond.setdefault(a2, {})[a1] = val
                    else:
                        cgr_dat_atom.setdefault(k['atoms'][0], {}).update(val)

        atom_dz = {}
        for k, l in enumerate(molecule['atoms'], start=1):
            atom_map = mapping[k]
            if k in cgr_dat_atom:
                atom_dat = cgr_dat_atom[k]
                if 'sp_charge' not in atom_dat:
                    atom_dat.update(s_charge=l['charge'], p_charge=l['charge'], sp_charge=l['charge'])
                if 'p_x' in atom_dat:
                    atom_dat['p_x'] += l['x']
                    atom_dat['p_y'] += l['y']
                    atom_dat['p_z'] += l['z']
                else:
                    atom_dat.update(p_x=l['x'], p_y=l['y'], p_z=l['z'])
                if 'dz' in atom_dat:
                    atom_dz[atom_map] = atom_dat.pop('dz')

                g.add_node(atom_map, mark=l['mark'], s_x=l['x'], s_y=l['y'], s_z=l['z'], **atom_dat)
                if atom_dat['p_z'] < .0001:
                    mdl_p_stereo = False
            else:
                g.add_node(atom_map, mark=l['mark'],
                           s_x=l['x'], s_y=l['y'], s_z=l['z'], p_x=l['x'], p_y=l['y'], p_z=l['z'],
                           s_charge=l['charge'], p_charge=l['charge'], sp_charge=l['charge'])

            if 'element' not in g.node[atom_map] and l['element'] not in ('A', '*'):
                g.node[atom_map]['element'] = l['element']
            if 'isotope' not in g.node[atom_map] and l['isotope']:
                a = elements.symbol(l['element'])
                g.node[atom_map]['isotope'] = max((a[x].abundance, x) for x in a.isotopes)[1] + l['isotope']
            if l['z'] != 0:
                mdl_s_stereo = False

        for k, l, m, s in molecule['bonds']:
            if k in cgr_dat_bond and l in cgr_dat_bond[k]:
                g.add_edge(mapping[k], mapping[l], **cgr_dat_bond[k][l])
            else:
                g.add_edge(mapping[k], mapping[l], s_bond=m, p_bond=m, sp_bond=m)

            if s in (1, 6):
                s_mark = 1 if s == 1 else -1
                atom_map = mapping[l]
                if mdl_s_stereo:
                    g.node[atom_map]['s_dz'] = s_mark
                if mdl_p_stereo and atom_map not in atom_dz:
                    g.node[atom_map]['p_dz'] = s_mark

        if mdl_p_stereo:
            for atom, dz in atom_dz.items():
                if dz:
                    g.node[atom]['p_dz'] = dz

        if colors:
            for k, v in colors.items():
                for a, c in cls.__parse_colors(k, v).items():
                    g.node[mapping[a]].update(c)
        return g

    __marks = {mark: ('s_%s' % mark, 'p_%s' % mark, 'sp_%s' % mark) for mark in ('neighbors', 'hyb', 'bond')}
    __cgrkeys = dict(extrabond=2, dynbond=2, dynatom=1, atomnotlist=1, atomlist=1, isotope=1,
                     atomhyb=1, atomneighbors=1, dynatomhyb=1, dynatomneighbors=1)


class CGRwrite:
    def __init__(self, extralabels=False, mark_to_map=False, _format='mdl'):
        self.__cgr = self.__to_cgr()
        self.__mark_to_map = mark_to_map
        self.__is_mdl = _format == 'mdl'
        self.__format_mol = self.__get_mol if self.__is_mdl else self.__get_mrv

        self.__atomprop = [('s_%s' % x, 'p_%s' % x, 'sp_%s' % x, 'atom%s' % x, 'dynatom%s' % x)
                           for x in (['stereo', 'hyb', 'neighbors'] if extralabels else ['stereo'])]

    def get_formatted_cgr(self, g):
        data = dict(meta=g.meta.copy())
        cgr_dat, extended, atoms, bonds = [], [], [], []
        renum, colors = {}, {}
        for n, (i, j) in enumerate(g.nodes(data=True), start=1):
            renum[i] = n
            charge, meta = self.__charge(j.get('s_charge'), j.get('p_charge'))
            element = j.get('element', 'A')

            if meta:
                meta['atoms'] = (n,)
                cgr_dat.append(meta)

            for s_key, p_key, _, a_key, d_key in self.__atomprop:
                meta = self.__get_state(j.get(s_key), j.get(p_key), a_key, d_key)
                if meta:
                    meta['atoms'] = (n,)
                    cgr_dat.append(meta)

            if 'isotope' in j:
                if isinstance(j['isotope'], list):
                    cgr_dat.append(dict(atoms=(n,), value=','.join(str(x) for x in j['isotope']), type='isotope'))
                else:
                    extended.append(dict(atom=n, value=j['isotope'], type='isotope'))

            for k in ('PHTYP', 'FFTYP', 'PCTYP', 'EPTYP', 'HBONDCHG', 'CNECHG'):
                for part, s_val in j.get('s_%s' % k, {}).items():
                    p_val = j['p_%s' % k][part]
                    meta = self.__get_state(s_val, p_val, k, 'dyn%s' % k)
                    if meta:
                        colors.setdefault(meta['type'], {}).setdefault(part, []).append('%d:%s' % (n, meta['value']))

            if isinstance(element, list):
                extended.append(dict(atom=n, value=j['element'], type='atomlist'))
                element = 'L'

            x, y, z = (j['x'], j['y'], j['z']) if self.__is_mdl else (j['x'] * 2, j['y'] * 2, j['z'] * 2)

            atoms.append(dict(map=j['mark'] if self.__mark_to_map else i, charge=charge,
                              element=element, mark=j['mark'], x=x, y=y, z=z))

        data['colors'] = {i: '\n'.join('%s %s' % (x, ' '.join(y)) for x, y in j.items()) for i, j in colors.items()}

        for i, l, j in g.edges(data=True):
            bond, cbond, btype = self.__cgr[j.get('s_bond')][j.get('p_bond')]
            if btype:
                cgr_dat.append({'value': cbond, 'type': btype, 'atoms': (renum[i], renum[l])})

            bonds.append((renum[i], renum[l], bond))

            meta = self.__get_state(j.get('s_stereo'), j.get('p_stereo'), 'bondstereo', 'dynbondstereo')
            if meta:
                meta['atoms'] = (renum[i], renum[l])
                cgr_dat.append(meta)

        data['CGR'] = self.__format_mol(atoms, bonds, extended, cgr_dat)
        return data

    @classmethod
    def __get_mol(cls, atoms, bonds, extended, cgr_dat):
        mol_prop = []
        for i in extended:
            if i['type'] == 'isotope':
                mol_prop.append('M  ISO  1 %3d %3d\n' % (i['atom'], i['value']))
            elif i['type'] == 'atomlist':
                atomslist, _type = (mendeleyset.difference(i['value']), 'T') \
                    if len(i['value']) > half_table else (i['value'], 'F')

                mol_prop.append('M  ALS %3d%3d %s %s\n' % (i['atom'], len(atomslist), _type,
                                                           ''.join('%-4s' % x for x in atomslist)))

        for j in count():
            sty = len(cgr_dat[j * 8:j * 8 + 8])
            if sty:
                stydat = ' '.join(['%3d DAT' % (x + j * 8) for x in range(1, 1 + sty)])
                mol_prop.append('M  STY  %d %s\n' % (sty, stydat))
            else:
                break

        for i, j in enumerate(cgr_dat, start=1):
            cx, cy = cls.__get_position([atoms[i - 1] for i in j['atoms']])
            mol_prop.append('M  SAL %3d%3d %s\n' % (i, len(j['atoms']), ' '.join(['%3d' % x for x in j['atoms']])))
            mol_prop.append('M  SDT %3d %s\n' % (i, j['type']))
            mol_prop.append('M  SDD %3d %10.4f%10.4f    DAU   ALL  0       0\n' % (i, cx, cy))
            mol_prop.append('M  SED %3d %s\n' % (i, j['value']))

        return ''.join(chain(("\n  CGRtools. (c) Dr. Ramil I. Nugmanov\n"
                             "\n%3s%3s  0  0  0  0            999 V2000\n" % (len(atoms), len(bonds)),),
                             ("%(x)10.4f%(y)10.4f%(z)10.4f %(element)-3s 0%(charge)3s  0  0  0  0  0"
                              "%(mark)3s  0%(map)3s  0  0\n" % i for i in atoms),
                             ("%3d%3d%3s  0  0  0  0\n" % i for i in bonds), mol_prop))

    @classmethod
    def __get_mrv(cls, atoms, bonds, extended, cgr_dat):
        isotope = {}
        atom_query = {}
        for i in extended:
            if i['type'] == 'isotope':
                isotope[i['atom']] = ' isotope="%d"' % i['value']
            elif i['type'] == 'atomlist':
                atom_query[i['atom']] = ' mrvQueryProps="L%s:"' % ''.join(('!%s' % x for x in
                                                                           mendeleyset.difference(i['value']))
                                                                          if len(i['value']) > half_table else
                                                                          i['value'])

        return ''.join(chain(('<atomArray>',),
                             ('<atom id="a{0}" elementType="{1[element]}" x3="{1[x]:.4f}" y3="{1[y]:.4f}" '
                              'z3="{1[z]:.4f}" mrvMap="{1[map]}" formalCharge="{1[charge]}"'
                              '{2}{3}{4}/>'.format(i, j, isotope.get(i, ''), atom_query.get(i, ''),
                                                   ' ISIDAmark="%s"' % j['mark'] if j['mark'] != '0' else '')
                              for i, j in enumerate(atoms, start=1)),
                             ('</atomArray><bondArray>',),
                             ('<bond id="b{0}" atomRefs2="a{1[0]} a{1[1]}" '
                              'order="{2[0]}"{2[1]}/>'.format(i, j, ('1', ' queryType="Any"') if k == '8' else (k, ''))
                              for i, (*j, k) in enumerate(bonds, start=1)),
                             ('</bondArray>',),
                             ('<molecule id="sg{0}" role="DataSgroup" fieldName="{1[type]}" fieldData="{1[value]}" '
                              'atomRefs="{2}" x="{3[0]}" y="{3[1]}" '
                              '/>'.format(i, j, ' '.join('a%d' % x for x in j['atoms']),
                                          cls.__get_position([atoms[i - 1] for i in j['atoms']]))
                              for i, j in enumerate(cgr_dat, start=1))))

    @staticmethod
    def __get_state(s, p, t1, t2):
        if isinstance(s, list):
            if s == p:
                _val = ','.join(x and str(x) or 'n' for x in s)
                _type = t1
            else:
                _val = ','.join('%s>%s' % (x or 'n', y or 'n') for x, y in zip(s, p) if x != y)
                _type = t2

        elif s != p:
            _val = '%s>%s' % (s or 'n', p or 'n')
            _type = t2
        else:
            _val = s
            _type = t1

        return _val and {'value': _val, 'type': _type}

    def __charge(self, s, p):
        charge = s
        if isinstance(s, list):
            charge = s[0]
            if s == p:
                meta = dict(type='dynatom', value='c0%s' % ','.join(str(x) for x in s[1:])) if len(s) > 1 else None
            elif s[0] != p[0]:
                meta = dict(type='dynatom', value='c%s' % ','.join(chain(['%+d' % (p[0] - charge)],
                                                                         ('%+d,%+d' % (x - charge, y - charge)
                                                                          for x, y in zip(s[1:], p[1:]) if x != y))))
            else:
                meta = None
        elif p != s:
            meta = dict(value='c%+d' % (p - s), type='dynatom')
        else:
            meta = None
        return toMDL.get(charge, 0) if self.__is_mdl else charge, meta

    @staticmethod
    def __to_cgr():
        ways = [None, 0, 1, 2, 3, 4, 9]
        rep = {None: 0}
        cgrdict = defaultdict(dict)
        for x, y in product(ways, repeat=2):
            cgrdict[x][y] = ('8', '%s>%s' % (rep.get(x, x), rep.get(y, y)), 'dynbond') if x != y else \
                ('8', 's', 'extrabond') if x == 9 else (str(rep.get(x, x)), None, False)
        return cgrdict

    @staticmethod
    def __get_position(cord):
        if len(cord) > 1:
            x = (cord[-1]['x'] + cord[0]['x']) / 2 + .2
            y = (cord[-1]['y'] + cord[0]['y']) / 2
            dy = cord[-1]['y'] - cord[0]['y']
            dx = cord[-1]['x'] - cord[0]['x']
            if dx > 0:
                y += -.2 if dy > 0 else .2
            elif dx < 0:
                y += -.2 if dy < 0 else .2
        else:
            x, y = cord[0]['x'] + .25, cord[0]['y']

        return x, y
