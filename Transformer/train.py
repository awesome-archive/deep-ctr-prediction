#-*- coding: UTF-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
import os
import random
from transformer import *
from input_fn import *
from sklearn.metrics import roc_auc_score
from metric import cal_group_auc, cross_entropy_loss
import glob
import numpy as np
#os.environ['CUDA_VISIBLE_DEVICES'] = '3'  #指定用哪块GPU

'''
A tensorflow implementation of Transformer

Ashish Vasmani et all.  "Attention is All You Need,"  In NIPS,2017.

Qiwei et all. "Behavior Sequence Transformer for E-commerce Recommendation in Alibaba" In Arxiv 1905.06874

@author: Qiao
'''

flags = tf.app.flags
flags.DEFINE_string("model_dir", "./models", "Base directory for the model")
flags.DEFINE_string("train_data_dir", "{20190205,20190206,20190207,20190208,20190209,20190210,20190211}/v1_tfrecord/", "dir for training data")
flags.DEFINE_string("eval_data_dir", "{20190212}/v1_tfrecord/", "dir for evaluation data")
flags.DEFINE_integer("batch_size", 512, "Training batch size")
flags.DEFINE_integer(name="num_epochs", short_name="ne", default=2, help="Training num epochs")
flags.DEFINE_float("learning_rate", 0.03, "Learning rate")
flags.DEFINE_string("hidden_units", "512,256,128", "number of units in each hidden layer for NN")
flags.DEFINE_integer("num_cross_layers", 4, "Number of cross layers")
flags.DEFINE_integer("save_checkpoints_steps", 20000, "Save checkpoints every steps")
flags.DEFINE_string("export_dir", "./exportmodels", "Path for exportmodels")
flags.DEFINE_boolean(name="evaluate_only", short_name="eo", default=False, help="evaluate only flag")
flags.DEFINE_boolean(name="use_cross", default=True, help="whether use cross layer")
flags.DEFINE_integer("predict_steps", 100000, "predict_steps*batch_size samples to evaluate")
flags.DEFINE_integer("transformer_num_units", 40, "embedding_size for transformer")
flags.DEFINE_integer("num_blocks", 1, "the number of multi-head attention we use")
flags.DEFINE_integer("num_heads", 8, "the number of heads for multi-head-attention")
flags.DEFINE_float("dropout_rate", 0.0, "the number of dropout rate for transformer")
FLAGS = flags.FLAGS

def export_model(model, export_dir, model_column_fn):
  """Export to SavedModel format.

  Args:
    model: Estimator object
    export_dir: directory to export the model.
    model_column_fn: Function to generate model feature columns.
  """
  columns = model_column_fn
  columns.append(tf.feature_column.numeric_column("user_id", default_value=123456, dtype=tf.int64))
  columns.append(tf.feature_column.numeric_column("label", default_value=0, dtype=tf.int64))
  other_feature_columns = {
      "product_id_att": tf.FixedLenFeature(shape=[1], dtype=tf.string),
      "creative_id_att": tf.FixedLenFeature(shape=[1], dtype=tf.string),
      "user_click_products_att": tf.FixedLenFeature(shape=[10], dtype=tf.string),
      "user_click_creatives_att": tf.FixedLenFeature(shape=[10], dtype=tf.string)
  }
  feature_spec = tf.feature_column.make_parse_example_spec(columns)
  feature_spec.update(other_feature_columns)
  example_input_fn = (
      tf.estimator.export.build_parsing_serving_input_receiver_fn(feature_spec))
  model.export_savedmodel(export_dir, example_input_fn)

def list_hdfs_dir(path):
    files = []
    sample_dir = "hdfs://yourhdfs" + path + "part*"
    sample_dir_script = "hadoop fs -ls " + sample_dir + " | awk  -F ' '  '{print $8}'"
    for dir_path in os.popen(sample_dir_script).readlines():
        dir_path = dir_path.strip()
        files.append(dir_path)
    return files

def model_predict(model, eval_input_fn, epoch):
    """Display evaluate result."""
    prediction_result = model.predict(eval_input_fn)

    click_sum = 0.0
    predictions = []
    user_id_list = []
    labels = []
    num_samples = FLAGS.batch_size * FLAGS.predict_steps
    num_pre_samples = 0
    print(num_samples)
    for pred_dict in prediction_result:
        # print(pred_dict)
        user_id = pred_dict['user_id'][0]
        p = pred_dict['probabilities'][0]
        label = float(pred_dict['label'][0])
        click_sum += p
        predictions.append(p)
        user_id_list.append(user_id)
        labels.append(label)
        if (p >= 0.5):
            num_pre_samples += 1

        if len(predictions) % (num_samples / 10) == 0:
            tf.logging.info('predict at step %d/%d', int(float(len(predictions)) / num_samples * FLAGS.predict_steps),
                            FLAGS.predict_steps)
        if len(predictions) >= num_samples:
            break

    #tf.metrics.precision
    # print(len(predictions))
    num_samples = len(predictions)
    print('the predicted positive samples is: ' + str(num_pre_samples))
    # Display evaluation metrics

    label_mean = sum(labels) / num_samples
    prediction_mean = sum(predictions) / num_samples
    loss = sum(cross_entropy_loss(labels, predictions)) / num_samples * FLAGS.batch_size
    auc = roc_auc_score(labels, predictions)
    group_auc = cal_group_auc(labels, predictions, user_id_list)

    predict_diff = np.array(predictions) - prediction_mean
    predict_diff_square_sum = sum(np.square(predict_diff))
    s_deviation = np.sqrt(predict_diff_square_sum / num_samples)
    c_deviation = s_deviation / prediction_mean

    true_positive_samples = (np.array(predictions) * np.array(labels) >= 0.5).tolist().count(True)
    false_positive_samples = (np.array(predictions) * (1 - np.array(labels)) >= 0.5).tolist().count(True)
    print(true_positive_samples)
    print(false_positive_samples)
    # precision = float(true_positive_samples)/(true_positive_samples+false_positive_samples)
    precision = 0
    false_negative_samples = (np.array(predictions) * np.array(labels) < 0.5).tolist().count(True)
    recall = float(true_positive_samples) / (true_positive_samples + false_negative_samples)
    print(false_negative_samples)
    tf.logging.info('Results at epoch %d/%d', (epoch + 1), FLAGS.num_epochs)
    tf.logging.info('-' * 60)
    tf.logging.info('label/mean: %s' % label_mean)
    tf.logging.info('predictions/mean: %s' % prediction_mean)
    tf.logging.info('total loss average batchsize: %s' % loss)
    tf.logging.info('standard deviation: %s' % s_deviation)
    tf.logging.info('coefficient of variation: %s' % c_deviation)
    tf.logging.info('precision: %s' % precision)
    tf.logging.info('recall: %s' % recall)
    tf.logging.info('auc: %s' % auc)
    tf.logging.info('group auc: %s' % group_auc)

def main(unused_argv):
  train_files = []
  eval_files = []
  if isinstance(FLAGS.train_data_dir, str):
    train_files = list_hdfs_dir(FLAGS.train_data_dir)

  if isinstance(FLAGS.eval_data_dir, str):
    eval_files = list_hdfs_dir(FLAGS.eval_data_dir)

  random.shuffle(train_files)
  feature_columns = build_model_columns()

  session_config = tf.ConfigProto(device_count={'GPU': 1, 'CPU': 20},
                                  inter_op_parallelism_threads=20,
                                  intra_op_parallelism_threads=20
                                  # log_device_placement=True
                                  )
  #session_config.gpu_options.per_process_gpu_memory_fraction = 0.32
  run_config = tf.estimator.RunConfig().replace(
      model_dir=FLAGS.model_dir,session_config=session_config, log_step_count_steps=1000, save_summary_steps=20000, save_checkpoints_secs=1000)

  model = tf.estimator.Estimator(
    model_fn=din_model_fn,
    params={
      'feature_columns': feature_columns,
      'hidden_units': FLAGS.hidden_units.split(','),
      'learning_rate': FLAGS.learning_rate,
      'num_cross_layers': FLAGS.num_cross_layers,
      'use_cross': FLAGS.num_cross_layers,
      "transformer_num_units": FLAGS.transformer_num_units,
      "num_blocks": FLAGS.num_blocks,
      "num_heads": FLAGS.num_heads,
      "dropout_rate": FLAGS.dropout_rate
    },
    config = run_config
  )
  train_input_fn = lambda: feature_input_fn(train_files, 1, True, FLAGS.batch_size)
  eval_input_fn = lambda: feature_input_fn(eval_files, 1, False, FLAGS.batch_size)  # not shuffle for evaluate
  
  #model_predict(model,eval_input_fn,0)
  for epoch in range(FLAGS.num_epochs):
      if FLAGS.evaluate_only == False:
          model.train(train_input_fn)
      print("*" * 100)
      #results = model.evaluate(input_fn=eval_input_fn, steps=6000)
      model_predict(model,eval_input_fn,epoch)


  # Export the model
  if FLAGS.export_dir is not None:
      export_model(model, FLAGS.export_dir, feature_columns)


if __name__ == "__main__":
  tf.logging.set_verbosity(tf.logging.INFO)
  tf.app.run(main=main)
