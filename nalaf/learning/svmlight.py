import os
import sys
import subprocess
from random import random
import tempfile
from nalaf import print_warning, print_verbose, print_debug, is_debug_mode


class SVMLightTreeKernels:
    """
    Base class for interaction with Alessandro Moschitti's Tree Kernels in SVM Light
    """

    def __init__(self, model_path=tempfile.NamedTemporaryFile().name, classification_threshold=0.0, use_tree_kernel=False, svmlight_dir_path=''):

        self.model_path = model_path
        """the model (path) to read from / write to"""
        print_debug("SVM-Light model file path: " + model_path)

        self.classification_threshold = classification_threshold

        self.use_tree_kernel = use_tree_kernel
        """whether to use tree kernels or not"""

        self.svmlight_dir_path = svmlight_dir_path
        """
        The directory where the executables svm_classify and svm_learn are located.
        Defaults to the empty string '', which then means that the svmlight executables must be in your binary path
        """

        executables_extension = '' if sys.platform.startswith('linux') or sys.platform.startswith('darwin') else '.exe'
        self.svm_learn_call = os.path.join(self.svmlight_dir_path, ('svm_learn' + executables_extension))
        self.svm_classify_call = os.path.join(self.svmlight_dir_path, ('svm_classify' + executables_extension))

        self.verbosity_level = str(1 if is_debug_mode else 0)


    def create_input_file(self, dataset, mode, features, minority_class=None, majority_class_undersampling=1.0):
        string = ''

        # Real counts vs Used ones after undersampling is applied
        num_pos_instances = [0, 0]
        num_neg_instances = [0, 0]
        num_unl_instances = [0, 0]

        allowed_features_keys = set(features.values())

        for edge in dataset.edges():
            if edge.target == 1:
                num_pos_instances[0] += 1
            elif edge.target == -1:
                num_neg_instances[0] += 1
            else:
                num_unl_instances[0] += 1

            if mode != 'train' or minority_class is None or edge.target == minority_class or random() <= majority_class_undersampling:
                if edge.target == 1:
                    num_pos_instances[1] += 1
                elif edge.target == -1:
                    num_neg_instances[1] += 1
                else:
                    num_unl_instances[1] += 1

                # http://svmlight.joachims.org "A class label of 0 indicates that this example should be classified using transduction"
                instance_label = '0' if mode == 'predict' else str(edge.target)

                string += instance_label

                if self.use_tree_kernel:
                    string += ' |BT| '
                    string += edge.part.sentence_parse_trees[edge.sentence_id]
                    string += ' |ET|'

                for key in sorted(edge.features.keys()):
                    if key in allowed_features_keys:
                        value = edge.features[key]
                        string += ' ' + str(key) + ':' + str(value)

                string += '\n'

        instancesfile = tempfile.NamedTemporaryFile('w', delete=False)
        print_debug("{}: svmlight instances file: {}".format(mode, instancesfile.name))
        instancesfile.write(string)
        instancesfile.flush()
        # Note, we do not close the file

        total_real = (num_pos_instances[0] + num_neg_instances[0] + num_unl_instances[0])
        total_used = (num_pos_instances[1] + num_neg_instances[1] + num_unl_instances[1])
        print_line = "{}: instances, REAL: #{} == #P: {} + #N: {} + #?: {} || vs. USED: #{} == #P: {} + #N: {} + #?: {}"
        print_debug(print_line.format(mode, total_real, num_pos_instances[0], num_neg_instances[0], num_unl_instances[0], total_used, num_pos_instances[1], num_neg_instances[1], num_unl_instances[1]))

        return instancesfile


    def learn(self, instancesfile, c=None):

        with instancesfile:

            if self.use_tree_kernel:
                callv = [
                    self.svm_learn_call,
                    '-v', self.verbosity_level,
                    '-t', '5',
                    '-T', '1',
                    '-W', 'S',
                    '-V', 'S',
                    '-C', '+',
                    '-c', str(c),
                    instancesfile.name,
                    self.model_path
                ]

            else:
                callv = [
                    self.svm_learn_call,
                    '-v', self.verbosity_level
                ]

                if c is not None:
                    callv = callv + ['-c', str(c)]

                callv = callv + [
                    instancesfile.name,
                    self.model_path
                ]

            print_debug("svm light learn parameters: " + ' '.join(callv))
            subprocess.call(callv)

            return self.model_path


    def classify(self, instancesfile):

        predictionsfile = tempfile.NamedTemporaryFile('r+', delete=False)
        print_debug("predict: svm predictions file: " + predictionsfile.name)

        callv = [
            self.svm_classify_call,
            '-v', '0',
            instancesfile.name,
            self.model_path,
            predictionsfile.name
        ]

        print_debug("svm light classify parameters: " + ' '.join(callv))
        exitcode = subprocess.call(callv)

        if exitcode != 0:
            raise Exception("Error when tagging: " + ' '.join(call))

        predictionsfile.flush()
        # Note, we do not close the file

        return predictionsfile


    def read_predictions(self, dataset, predictionsfile, classification_threshold=None):
        classification_threshold = classification_threshold if classification_threshold is not None else self.classification_threshold

        values = []
        with predictionsfile:
            predictionsfile.seek(0)

            for line in predictionsfile:
                prediction = float(line.strip())
                print_verbose("  pred: " + str(prediction))

                if prediction > classification_threshold:
                    values.append(+1)
                else:
                    values.append(-1)

            if (len(values) > 1):
                for index, edge in enumerate(dataset.edges()):
                    edge.target = values[index]
            else:
                if (next(dataset.edges(), None)):
                    raise Exception("EMPTY PREDICTIONS FILE -- This may be due to too small dataset or too few of features. Predictions file: " + predictionsfile.name)

        return dataset.form_predicted_relations()
