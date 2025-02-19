# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Serves as a common "main" function for all the SavedModel tests.

There is a fair amount of setup needed to initialize tensorflow and get it
into a proper TF2 execution mode. This hides that boilerplate.
"""

import tempfile
from absl import app
from absl import flags
from absl import logging
import tensorflow.compat.v1 as tf

from tensorflow.python import pywrap_mlir  # pylint: disable=g-direct-tensorflow-import

# Use /tmp to make debugging the tests easier (see README.md)
flags.DEFINE_string('save_model_path', '', 'Path to save the model to.')
FLAGS = flags.FLAGS


def set_tf_options():
  # Default TF1.x uses reference variables that are not supported by SavedModel
  # v1 Importer. To use SavedModel V1 Importer, resource variables should be
  # enabled.
  tf.enable_resource_variables()
  tf.compat.v1.disable_eager_execution()


# This function needs to take a "create_module_fn", as opposed to just the
# module itself, because the creation of the module has to be delayed until
# after absl and tensorflow have run various initialization steps.
def do_test(create_signature,
            canonicalize=False,
            show_debug_info=False,
            use_lite=False,
            lift_variables=True):
  """Runs test.

  1. Performs absl and tf "main"-like initialization that must run before almost
     anything else.
  2. Converts signature_def_map to SavedModel V1
  3. Converts SavedModel V1 to MLIR
  4. Prints the textual MLIR to stdout (it is expected that the caller will have
     FileCheck checks in its file to check this output).

  This is only for use by the MLIR SavedModel importer tests.

  Args:
    create_signature: A functor that return signature_def_map, init_op and
      assets_collection. signature_def_map is a map from string key to
      signature_def. The key will be used as function name in the resulting
      MLIR.
    canonicalize: If true, canonicalizer will be run on the resulting MLIR.
    show_debug_info: If true, shows debug locations in the resulting MLIR.
    use_lite: If true, importer will not do any graph transformation such as
      lift variables.
    lift_variables: If false, no variable lifting will be done on the graph.
  """

  # Make LOG(ERROR) in C++ code show up on the console.
  # All `Status` passed around in the C++ API seem to eventually go into
  # `LOG(ERROR)`, so this makes them print out by default.
  logging.set_stderrthreshold('error')

  def app_main(argv):
    """Function passed to absl.app.run."""
    if len(argv) > 1:
      raise app.UsageError('Too many command-line arguments.')
    save_model_path = FLAGS.save_model_path or tempfile.mktemp(
        suffix='.saved_model')
    signature_def_map, init_op, assets_collection = create_signature()

    sess = tf.Session()
    sess.run(tf.initializers.global_variables())
    builder = tf.saved_model.builder.SavedModelBuilder(save_model_path)
    builder.add_meta_graph_and_variables(
        sess, [tf.saved_model.tag_constants.SERVING],
        signature_def_map,
        main_op=init_op,
        assets_collection=assets_collection,
        strip_default_attrs=True)
    builder.save()

    logging.info('Saved model to: %s', save_model_path)
    exported_names = ''
    upgrade_legacy = True
    if use_lite:
      mlir = pywrap_mlir.experimental_convert_saved_model_v1_to_mlir_lite(
          save_model_path, exported_names,
          ','.join([tf.saved_model.tag_constants.SERVING]),
          upgrade_legacy, show_debug_info)
      # We don't strictly need this, but it serves as a handy sanity check
      # for that API, which is otherwise a bit annoying to test.
      # The canonicalization shouldn't affect these tests in any way.
      mlir = pywrap_mlir.experimental_run_pass_pipeline(mlir,
                                                        'tf-standard-pipeline',
                                                        show_debug_info)
    else:
      mlir = pywrap_mlir.experimental_convert_saved_model_v1_to_mlir(
          save_model_path, exported_names,
          ','.join([tf.saved_model.tag_constants.SERVING]),
          lift_variables, upgrade_legacy, show_debug_info)

    if canonicalize:
      mlir = pywrap_mlir.experimental_run_pass_pipeline(mlir, 'canonicalize',
                                                        show_debug_info)
    print(mlir)

  app.run(app_main)
