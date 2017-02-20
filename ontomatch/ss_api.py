import sys
from algebra import API
from knowledgerepr import fieldnetwork
from modelstore.elasticstore import StoreHandler
from ontomatch import ss_utils as SS
from knowledgerepr.networkbuilder import LSHRandomProjectionsIndex
from ontomatch import glove_api
from collections import defaultdict
from ontomatch.onto_parser import OntoHandler
from inputoutput import inputoutput as io
from datasketch import MinHash, MinHashLSH
import numpy as np
from nltk.corpus import stopwords
from dataanalysis import nlp_utils as nlp
import time
from ontomatch import matcher_lib as matcherlib
from ontomatch.matcher_lib import MatchingType

# Have a list of accepted formats in the ontology parser


class SSAPI:

    def __init__(self, network, store_client, schema_sim_index, content_sim_index):
        self.network = network
        self.store_client = store_client
        self.schema_sim_index = schema_sim_index
        self.content_sim_index = content_sim_index
        self.srql = API(self.network, self.store_client)
        self.krs = []
        self.kr_handlers = dict()

        # SS indexes
        self.num_vectors_tables = 0  # Total number of semantic vectors for tables
        self.sskey_to_ss = dict()  # ss_key to (table_name, semantic_vectors)
        self.sskey_to_vkeys = dict()  # ss_key to [vector_keys]
        self.vkey_to_sskey = dict()  # vector_key to ss_key (the ss_key that contains vector_key)
        vector_feature_dim = glove_api.get_lang_model_feature_size()
        self.ss_lsh_idx = LSHRandomProjectionsIndex(vector_feature_dim)

    def add_krs(self, kr_name_paths, parsed=True):
        """
        Register the given KR for processing. Validate accepted format, etc
        # TODO: make this more usable
        :param krs: the list of (kr_name, kr_path)
        :return:
        """
        for kr_name, kr_path in kr_name_paths:
            self.krs.append((kr_name, kr_path))
            o = OntoHandler()
            if parsed:  # the ontology was preprocessed
                o.load_ontology("cache_onto/" + kr_name + ".pkl")
            else:
                o.parse_ontology(kr_path)
                o.store_ontology("cache_onto/" + kr_name + ".pkl")
            self.kr_handlers[kr_name] = o

    def __compare_content_signatures(self, kr_name, signatures):
        positive_matches = []
        for class_name, mh_sig in signatures:
            mh_obj = MinHash(num_perm=512)
            mh_array = np.asarray(mh_sig, dtype=int)
            mh_obj.hashvalues = mh_array
            res = self.content_sim_index.query(mh_obj)
            for r_nid in res:
                (nid, db_name, source_name, field_name) = self.network.get_info_for([r_nid])[0]
                # matching from db attr to name
                matching = ((db_name, source_name, field_name), (kr_name, class_name))
                positive_matches.append(matching)
        return positive_matches

    def __build_content_sim(self, threshold):
        # Build a content similarity index
        # Content_sim text relation (minhash-based)
        start_text_sig_sim = time.time()
        st = time.time()
        mh_signatures = self.store_client.get_all_mh_text_signatures()
        et = time.time()
        print("Time to extract minhash signatures from store: {0}".format(str(et - st)))
        print("!!3 " + str(et - st))

        content_index = MinHashLSH(threshold=threshold, num_perm=512)
        mh_sig_obj = []
        # Create minhash objects and index
        for nid, mh_sig in mh_signatures:
            mh_obj = MinHash(num_perm=512)
            mh_array = np.asarray(mh_sig, dtype=int)
            mh_obj.hashvalues = mh_array
            content_index.insert(nid, mh_obj)
            mh_sig_obj.append((nid, mh_obj))
        end_text_sig_sim = time.time()
        print("Total text-sig-sim (minhash): {0}".format(str(end_text_sig_sim - start_text_sig_sim)))
        print("!!4 " + str(end_text_sig_sim - start_text_sig_sim))

        self.content_sim_index = content_index

    def find_matchings(self):
        """
        Find matching for each of the different possible categories
        :return: list of matchings
        """
        all_matchings = dict()

        # Build content sim
        self.__build_content_sim(0.4)

        # L1: [class] -> attr.content
        st = time.time()
        print("Finding L1 matchings...")
        kr_class_signatures = []
        l1_matchings = []
        for kr_name, kr_handler in self.kr_handlers.items():
            kr_class_signatures += kr_handler.get_classes_signatures()
            l1_matchings += self.__compare_content_signatures(kr_name, kr_class_signatures)

        print("Finding L1 matchings...OK, "+str(len(l1_matchings))+" found")
        et = time.time()
        print("Took: " + str(et-st))
        all_matchings[MatchingType.L1_CLASSNAME_ATTRVALUE] = l1_matchings

        for match in l1_matchings:
            print(match)

        # L2: [class.data] -> attr.content
        print("Finding L2 matchings...")
        st = time.time()
        kr_classdata_signatures = []
        l2_matchings = []
        #for kr_name, kr_handler in self.kr_handlers.items():
        #    kr_classdata_signatures += kr_handler.get_class_data_signatures()
        #    l2_matchings = self.__compare_content_signatures(kr_name, kr_classdata_signatures)
        print("Finding L2 matchings...OK, " + str(len(l2_matchings)) + " found")
        et = time.time()
        print("Took: " + str(et - st))
        all_matchings[MatchingType.L2_CLASSVALUE_ATTRVALUE] = l2_matchings

        #for match in l2_matchings:
        #    print(match)

        # L3: [class.context] -> relation
        print("Finding L3 matchings...")
        st = time.time()
        #l3_matchings = self.find_coarse_grain_hooks_n2()
        l3_matchings = []
        print("Finding L3 matchings...OK, " + str(len(l3_matchings)) + " found")
        et = time.time()
        print("Took: " + str(et - st))
        all_matchings[MatchingType.L3_CLASSCTX_RELATIONCTX] = l3_matchings

        #for match in l3_matchings:
        #    print(match)

        # L4: [Relation names] -> [Class names] (syntax)
        print("Finding L4 matchings...")
        st = time.time()
        l4_matchings = matcherlib.find_relation_class_name_matchings()
        print("Finding L4 matchings...OK, " + str(len(l4_matchings)) + " found")
        et = time.time()
        print("Took: " + str(et - st))
        all_matchings[MatchingType.L4_CLASSNAME_RELATIONNAME_SYN] = l4_matchings

        #for match in l4_matchings:
        #    print(match)

        # L4.2: [Relation names] -> [Class names] (semantic)
        print("Finding L42 matchings...")
        st = time.time()
        l42_matchings = matcherlib.find_relation_class_name_sem_matchings()
        print("Finding L42 matchings...OK, " + str(len(l42_matchings)) + " found")
        et = time.time()
        print("Took: " + str(et - st))
        all_matchings[MatchingType.L42_CLASSNAME_RELATIONNAME_SEM] = l42_matchings

        #for match in l42_matchings:
        #    print(match)

        # L5: [Attribute names] -> [Class names] (syntax)
        print("Finding L5 matchings...")
        st = time.time()
        l5_matchings = matcherlib.find_relation_class_attr_name_matching()
        print("Finding L5 matchings...OK, " + str(len(l5_matchings)) + " found")
        et = time.time()
        print("Took: " + str(et - st))
        all_matchings[MatchingType.L5_CLASSNAME_ATTRNAME_SYN] = l5_matchings

        #for match in l5_matchings:
        #    print(match)

        # L52: [Attribute names] -> [Class names] (semantic)
        print("Finding L52 matchings...")
        st = time.time()
        l52_matchings = matcherlib.find_relation_class_attr_name_sem_matchings()
        print("Finding L52 matchings...OK, " + str(len(l52_matchings)) + " found")
        et = time.time()
        print("Took: " + str(et - st))
        all_matchings[MatchingType.L52_CLASSNAME_ATTRNAME_SEM] = l52_matchings

        #for match in l52_matchings:
        #    print(match)

        # L6: [Relations] -> [Class names] (semantic groups)
        print("Finding L6 matchings...")
        st = time.time()
        l6_matchings = matcherlib.find_sem_coh_matchings()
        print("Finding L6 matchings...OK, " + str(len(l6_matchings)) + " found")
        et = time.time()
        print("Took: " + str(et - st))
        all_matchings[MatchingType.L6_CLASSNAME_RELATION_SEMSIG] = l6_matchings

        # for match in l52_matchings:
        #    print(match)

        total_matchings_pre_combined = 0
        for values in all_matchings.values():
            total_matchings_pre_combined += len(values)
        print("ALL: " + str(total_matchings_pre_combined))
        combined_matchings, l4_matchings = matcherlib.combine_matchings(all_matchings)
        print("COM: " + str(len(combined_matchings)))

        print("l6 matchings")
        for m in l6_matchings:
            print(m)

        # L7: [Attribute names] -> [class names] (content - fuzzy naming)
        print("Finding L7 matchings...")
        st = time.time()
        l7_matchings = matcherlib.find_hierarchy_content_fuzzy()
        print("Finding L7 matchings...OK, " + str(len(l7_matchings)) + " found")
        et = time.time()
        print("Took: " + str(et - st))
        all_matchings[MatchingType.L7_CLASSNAME_ATTRNAME_FUZZY] = l7_matchings

        return combined_matchings

    def find_coarse_grain_hooks_n2(self):
        matchings = []
        table_ss = SS.generate_table_vectors(None, network=self.network)  # get semantic signatures of tables
        class_ss = self._get_kr_classes_vectors()
        total = len(class_ss.items())
        idx = 0
        for class_name, class_vectors in class_ss.items():
            print("Checking: " + str(idx) + "/" + str(total) + " : " + str(class_name))
            # for (dbname, table_name), table_vectors in ...
            for db_table, table_vectors in table_ss.items():
                db_name, table_name = db_table
                sim = SS.compute_semantic_similarity(class_vectors, table_vectors)
                print(str(table_name) + " -> " + str(class_name) + " : " + str(sim))
                if sim > 0.85:
                    match = ((db_name, table_name, "_"), class_name)
                    matchings.append(match)
        return matchings

    def _get_kr_classes_vectors(self):
        class_vectors = dict()
        for kr_name, kr in self.kr_handlers.items():
            for class_name in kr.classes_id():
                success, ret = kr.bow_repr_of(class_name, class_id=True)  # Get bag of words representation
                if success:
                    label, bow = ret
                    seen_tokens = []  # filtering out already seen tokens
                    sem_vectors = []
                    for el in bow:
                        el = el.replace('_', ' ')
                        tokens = el.split(' ')
                        for token in tokens:
                            token = token.lower()
                            if token not in stopwords.words('english'):
                                seen_tokens.append(token)
                                sem_vector = glove_api.get_embedding_for_word(token)
                                if sem_vector is not None:
                                    sem_vectors.append(sem_vector)
                    if len(sem_vectors) > 0:  # otherwise just no context generated for this class
                        class_vectors[kr.name_of_class(class_name)] = sem_vectors
                else:
                    print(ret)
        return class_vectors

    def find_links(self, matchings):
        """
        Given existings matchings and parsed KRs, find existing links in the data
        :return: a list of found links. Each element in the list is a tuple with 3 components:
        ((el1), relation_name, (el2))
        Each element (el1 and el2) are a locator of the attribute/relation involved in the link
        """

        # There are two kinds of links we discover, those between attributes, and those between relations

        # Iterate over matchings
        # For each matching, take ontology class (2nd element of the tuple), and take its hierarchy in the ontology

        # is any other element in the ontology involved in a matching?
        # YES -> create a link (is_a) between the elements in the schema (reverse mapping the onto class)
        # is any other element in the properties involved in a matching? (object property in OWL)
        # YES -> create a link (objectProperty name) between the elements in the schema

        # NOTES:
        # matchings always point from an element int he schema to a class in an ontology
        # for this function to work efficiently, probably one wants to create a map from onto class to schema element
        # note that the links are between elements of the schema (no ontologies involved here)

        return

    def find_coarse_grain_hooks(self):
        # FIXME: deprecated?
        """
        Given the model and the parsed KRs, find coarse grain hooks and register them
        :return:
        """

        # TODO: should we do this beforehand?
        # Get ss for each relation in S
        table_ss = SS.generate_table_vectors(self.network)  # get semantic signatures of tables
        ss_key = 0
        for k, v in table_ss.items():
            self.sskey_to_ss[ss_key] = (k, v)  # assign a key to each semantic signature (tablename - sem vectors)
            vkey = 0
            vkeys = []
            for s_vector in v:
                self._lsh_index_vector(s_vector, vkey)  # LSH-index s_vector with key vkey
                self.vkey_to_sskey[vkey] = ss_key  # Keep inverse index from vector to its signature
                vkey += 1
                vkeys.append(vkey)
                self.num_vectors_tables += 1  # One more vector
            self.sskey_to_vkeys[ss_key] = vkeys  # for each signature, keep the list of vector keys it contains
            ss_key += 1

        # Get ss for each class in Cgg
        # TODO:

        # Iterate smaller index (with fewer vectors) and retrieve candidates for coarse-grain hooks
        for sskey, ss in self.sskey_to_ss.items():
            (table_name, semantic_vectors) = ss
            accum = defaultdict(list)
            for s_vector in semantic_vectors:
                neighbors = self._lsh_query(s_vector)
                for (data, key, value) in neighbors:
                    sskey = self.vkey_to_sskey[key]
                    accum[sskey].append(1)
            # We process accum, that contains keys for the ss that had at least one neighbor
            # TODO: we need the new expression here

        return

    def _lsh_index_vector(self, vector, key):
        # FIXME: deprecated?
        """
        Index the vector with the associated key
        :param vector:
        :param key:
        :return:
        """
        self.ss_lsh_idx.index(vector, key)

    def _lsh_query(self, vector):
        # FIXME: deprecated?
        """
        Query the LSH index
        :param vector:
        :return: (data, key, value)
        """
        n = self.ss_lsh_idx.query(vector)
        return n

    def write_semantics(self):
        """
        Push found mappings, links and constraints (properties) to the model
        Reconciliation mechanism goes here (or does it go model side?)
        :return:
        """
        return

    """
    ### OUTPUT FUNCTIONS
    """

    def output_registered_krs(self):
        return

    def output_krs_statistics(self):
        return

    def output_coarse_grain_hooks(self):
        return

    def output_mappings(self):
        return

    def output_links(self):
        return


def test(path_to_serialized_model):
    # Deserialize model
    network = fieldnetwork.deserialize_network(path_to_serialized_model)
    # Create client
    store_client = StoreHandler()

    # Load glove model
    print("Loading language model...")
    path_to_glove_model = "../glove/glove.6B.100d.txt"
    glove_api.load_model(path_to_glove_model)
    print("Loading language model...OK")

    # Retrieve indexes
    schema_sim_index = io.deserialize_object(path_to_serialized_model + 'schema_sim_index.pkl')
    content_sim_index = io.deserialize_object(path_to_serialized_model + 'content_sim_index.pkl')

    # Create ontomatch api
    om = SSAPI(network, store_client, schema_sim_index, content_sim_index)
    # Load parsed ontology
    om.add_krs([("efo", "cache_onto/efo.pkl")], parsed=True)

    matchings = om.find_matchings()
    #matchings = om.find_sem_coh_matchings()

    for m in matchings:
        print(m)
    exit()

    total_matchings = 0
    for k, v in matchings.items():
        total_matchings += len(v)
        print(str(k) + ": " + str(len(v)))
    print("total matchings: " + str(total_matchings))
    print("####")
    for m, v in matchings.items():
        print(m)
        for el in v:
            print(el)

    return om


def main(path_to_serialized_model):
    # Deserialize model
    network = fieldnetwork.deserialize_network(path_to_serialized_model)
    # Create client
    store_client = StoreHandler()

    # Retrieve indexes
    schema_sim_index = io.deserialize_object(path_to_serialized_model + 'schema_sim_index.pkl')
    content_sim_index = io.deserialize_object(path_to_serialized_model + 'content_sim_index.pkl')

    om = SSAPI(network, store_client, schema_sim_index, content_sim_index)

    om.add_krs([("dbpedia", "cache_onto/dbpedia.pkl")], parsed=True)

    return om


def test_find_semantic_sim():
    # Load onto
    om = SSAPI(None, None, None, None)
    # Load parsed ontology
    om.add_krs([("dbpedia", "cache_onto/schemaorg.pkl")], parsed=True)

    # Load glove model
    print("Loading language model...")
    path_to_glove_model = "../glove/glove.6B.100d.txt"
    glove_api.load_model(path_to_glove_model)
    print("Loading language model...OK")

    print("Loading ontology classes...")
    names = []
    # Load classes
    for kr_name, kr_handler in om.kr_handlers.items():
        all_classes = kr_handler.classes()
        for cl in all_classes:
            cl = nlp.camelcase_to_snakecase(cl)
            cl = cl.replace('-', ' ')
            cl = cl.replace('_', ' ')
            cl = cl.lower()
            svs = []
            for token in cl.split():
                if token not in stopwords.words('english'):
                    sv = glove_api.get_embedding_for_word(token)
                    if sv is not None:
                        svs.append(sv)
            names.append(('class', cl, svs))
    print("Loading ontology classes...OK")

    while True:
        # Get words
        i = input("introduce two words separated by space to get similarity. EXIT to exit")
        tokens = i.split(' ')
        if tokens[0] == "EXIT":
            print("bye!")
            break
        svs = []
        for t in tokens:
            sv = glove_api.get_embedding_for_word(t)
            if sv is not None:
                svs.append(sv)
            else:
                print("No vec for : " + str(t))
        for _, cl, vecs in names:
            sim = SS.compute_semantic_similarity(svs, vecs)
            if sim > 0.4:
                print(str(cl) + " -> " + str(sim))

if __name__ == "__main__":

    #test_find_semantic_sim()
    #exit()

    test("../models/chembl21/")
    exit()

    print("SSAPI")

    path_to_model = ""
    path_to_glove_model = ""
    if len(sys.argv) >= 4:
        path_to_model = sys.argv[2]
        path_to_glove_model = sys.argv[4]

    else:
        print("USAGE")
        print("db: the name of the model to use")
        print("lm: the name of the language model to use")
        exit()

    print("Loading language model...")
    glove_api.load_model(path_to_glove_model)
    print("Loading language model...OK")

    om = main(path_to_model)

    # do things with om now, for example, for testing

