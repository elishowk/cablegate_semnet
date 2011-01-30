# -*- coding: utf-8 -*-
#  Copyright (C) 2010 elishowk@nonutc.fr
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
import logging
logging.basicConfig(level=logging.DEBUG, format="%(levelname)-8s %(message)s")

import math
from os.path import join
import re
import itertools
import nltk
import cPickle
from nltk import PorterStemmer

from neo4jrestclient.client import GraphDatabase
from mongodbhandler import CablegateDatabase

from cablenetwork import add_node, set_node_attr, get_node, updateEdge
from cabletokenizer import NGramizer
from datamodel import initEdges, addEdge
import filtering
import stopwords

class CableExtract(object):
    """
    Reads all database entries to :
    - extract and filter NGrams from content
    - write the Document-NGram network
    """
    def __init__(self, config, overwrite=True):
        self.mongodb = CablegateDatabase(config['general']['mongodb'])["cablegate"]
        self.graphdb = GraphDatabase(config['general']['neo4j'])
        self.config = config
        filters = self._get_extraction_filters()
        postagger = cPickle.load(open(self.config['extraction']['tagger'],"r"))
        extract_gen = self.extract(NGramizer(self.config), filters, postagger, overwrite)
        try:
            while 1:
                cable = extract_gen.next()
                self.mongodb.save(cable)
                self.update_cooc(cable)
        except StopIteration, si:
            return

    def update_cooc(self, cable):
        ngramcache={}
        for ng1, ng2 in itertools.combinations(cable['edges']['NGram'].keys(), 2):
            if ng1 not in ngramcache:
                ngramcache[ng1] = self.mongodb.ngrams.find_one({'_id': ng1})
            if ng2 not in ngramcache:
                ngramcache[ng2] = self.mongodb.ngrams.find_one({'_id': ng2})
            ngramcache[ng1] = addEdge(ngramcache[ng1], "NGram", ng2, 1)
            ngramcache[ng2] = addEdge(ngramcache[ng2], "NGram", ng1, 1)
        for ngram in ngramcache.values():
            self.mongodb.ngrams.save(ngram)

    def extract(self, ngramizer, filters, postagger, overwrite):
        """
        gets the all cables from storage then extract n-grams and produce networks edges and weights
        """
        if overwrite is True and "ngrams" in self.mongodb.collection_names():
            self.mongodb.ngrams.remove()

        for cable in self.mongodb.cables.find(timeout=False):
            if cable is None:
                logging.warning("cable %d not found in the database, skipping"%cable_id)
                continue
            if overwrite is True:
                cable = initEdges(cable)
            # extract and filter ngrams
            ngramizer.extract(
                cable,
                filters,
                postagger,
                PorterStemmer()
            )
            yield cable

    def _get_extraction_filters(self):
        """
        returns extraction filters
        """
        filters = [filtering.WordSizeFilter(
            config = {
                'rules': {
                    'minWordSize': self.config['extraction']['minWordSize']
                }
            }
        )]
        filters += [filtering.PosTagValid(
            config = {
                'rules': re.compile(self.config['extraction']['postag_valid'])
            }
        )]
        filters += [stopwords.StopWords(
            "file://%s"%join(
                self.config['general']['basedirectory'],
                self.config['general']['shared'],
                self.config['extraction']['stopwords']
            )
        )]
        return filters