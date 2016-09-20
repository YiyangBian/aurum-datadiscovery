from modelstore.elasticstore import StoreHandler
from knowledgerepr import fieldnetwork
from knowledgerepr import networkbuilder
from knowledgerepr.networkbuilder import FieldNetwork

import sys
import time


def main(output_path=None):
    start_all = time.time()
    network = FieldNetwork()
    store = StoreHandler()

    # Get all fields from store
    fields_gen = store.get_all_fields()

    # Network skeleton and hierarchical relations (table - field), etc
    start_schema = time.time()
    network.init_meta_schema(fields_gen)
    end_schema = time.time()
    print("Total skeleton: {0}".format(str(end_schema - start_schema)))

    # Schema_sim relation
    start_schema_sim = time.time()
    networkbuilder.build_schema_sim_relation(network)
    end_schema_sim = time.time()
    print("Total schema-sim: {0}".format(str(end_schema_sim - start_schema_sim)))

    # Entity_sim relation
    start_entity_sim = time.time()
    #fields, entities = store.get_all_fields_entities()
    #networkbuilder.build_entity_sim_relation(network, fields, entities)
    end_entity_sim = time.time()
    print("Total entity-sim: {0}".format(str(end_entity_sim - start_entity_sim)))

    # Content_sim text relation
    start_text_sig_sim = time.time()
    st = time.time()
    text_signatures = store.get_all_fields_text_signatures(network)
    et = time.time()
    print("Time to extract signatures from store: {0}".format(str(et - st)))

    networkbuilder.build_content_sim_relation_text_lsa(network, text_signatures)
    end_text_sig_sim = time.time()
    print("Total text-sig-sim: {0}".format(str(end_text_sig_sim - start_text_sig_sim)))

    # Content_sim num relation
    start_num_sig_sim = time.time()
    id_sig = store.get_all_fields_num_signatures()
    networkbuilder.build_content_sim_relation_num(network, id_sig)
    end_num_sig_sim = time.time()
    print("Total num-sig-sim: {0}".format(str(end_num_sig_sim - start_num_sig_sim)))

    # Primary Key / Foreign key relation
    start_pkfk = time.time()
    networkbuilder.build_pkfk_relation(network)
    end_pkfk = time.time()
    print("Total PKFK: {0}".format(str(end_pkfk - start_pkfk)))

    #topk = 100
    #degree = network.fields_degree(topk)
    #for node, val in degree:
    #    print("N - " + str(node) + " degree: " + str(val))

    #import networkx as nx
    #from matplotlib.pyplot import show
    #nx.write_gml(network._get_underlying_repr(), "gexfTEST.gml")
    #nx.draw(network._get_underlying_repr())
    #show()

    end_all = time.time()
    print("Total time: {0}".format(str(end_all - start_all)))

    path = "test/datagov/"
    if output_path is not None:
        path = output_path
    fieldnetwork.serialize_network(network, path)

    print("DONE!")


def plot_num():
    network = FieldNetwork()
    store = StoreHandler()
    fields, num_signatures = store.get_all_fields_num_signatures()

    xaxis = []
    yaxis = []
    numpoints = 0
    for x, y in num_signatures:
        numpoints = numpoints + 1
        xaxis.append(x)
        yaxis.append(y)
    print("Num points: " + str(numpoints))
    import matplotlib.pyplot as plt
    plt.plot(xaxis, yaxis, 'ro')
    plt.axis([0, 600000, 0, 600000])
    #plt.axis([0, 10000, 0, 10000])
    #plt.axis([0, 500, 0, 500])
    plt.show()


if __name__ == "__main__":
    path = None
    if len(sys.argv) == 3:
        path = sys.argv[2]
    else:
        print("USAGE: ")
        print("python networkbuildercoordinator.py --opath <path>")
        print("where opath must be writable by the process")
        exit()
    main(path)

    #test_read_store()

    #test()
    #plot_num()
    #test_cardinality_propagation()
