import pyarrow as pa
import pyarrow.parquet as pq
import os
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout, Flatten
from tensorflow.keras.layers import Conv2D, MaxPooling2D
import requests
import argparse

import sys
sys.path.insert(0, os.path.abspath("/usr/local/lib/python3.6/dist-packages"))
from dkube.sdk import *

parser = argparse.ArgumentParser()
parser.add_argument("--url", dest = 'url', default=None, type = str, help="setup URL")
parser.add_argument("--epochs", dest = 'epochs', type = int, default = 5, help="no. of epochs")
parser.add_argument("--batch_size", dest = 'batch_size', type = int, default = 128, help="no. of epochs")

def log_metrics(key, value, epoch, step):
    url = "http://dkube-exporter.dkube:9401/mlflow-exporter"
    train_metrics = {}
    train_metrics['mode']="train"
    train_metrics['key'] = key
    train_metrics['value'] = value
    train_metrics['epoch'] = epoch
    train_metrics['step'] = step
    train_metrics['jobid']=os.getenv('DKUBE_JOB_ID')
    train_metrics['run_id']=os.getenv('DKUBE_JOB_UUID')
    train_metrics['username']=os.getenv('DKUBE_USER_LOGIN_NAME')
    requests.post(url, json = train_metrics)
    
def get_one_hot(targets, nb_classes):
    res = np.eye(nb_classes)[np.array(targets).reshape(-1)]
    return res.reshape(list(targets.shape)+[nb_classes])

inp_path = '/opt/dkube/input/'
out_path = '/opt/dkube/output/'
filename = 'featureset.parquet'
num_classes = 10
input_shape = (28,28,1)

global FLAGS
FLAGS,unparsed=parser.parse_known_args()
epochs = FLAGS.epochs
batch_size = FLAGS.batch_size
dkubeURL = FLAGS.url
authToken = os.getenv('DKUBE_USER_ACCESS_TOKEN')
# Dkube API calling
api = DkubeApi(URL=dkubeURL, token=authToken)
# Featureset API call
featureset = DkubeFeatureSet()
# Featureset input path update
featureset.update_features_path(path=inp_path)
# Reading featureset, output: response json with data
data  = featureset.read()

# Fetching data from response
feature_df = data["data"]

y = feature_df['label'].values
x = feature_df.drop('label', 1).values

x = x.reshape(x.shape[0], 28, 28, 1)

y = get_one_hot(y, 10)

# Defining model
model = Sequential()
model.add(Conv2D(32, kernel_size=(3, 3),
                 activation='relu',
                 input_shape=input_shape))
model.add(Conv2D(64, (3, 3), activation='relu'))
model.add(MaxPooling2D(pool_size=(2, 2)))
model.add(Flatten())
model.add(Dense(128, activation='relu'))
model.add(Dense(num_classes, activation='softmax'))

model.compile(loss=tf.keras.losses.categorical_crossentropy,
              optimizer='adam',
              metrics=['accuracy'])

# Model training
history = model.fit(x, y,
              batch_size=batch_size,
              epochs=epochs,
              verbose=1)

# logging metrics into Dkube
if 'acc' in history.history.keys():
    for i in range(1, epochs + 1):
        log_metrics('accuracy', float(history.history['acc'][i-1]), i, i)
        log_metrics('loss', float(history.history['loss'][i-1]), i, i)
        print("accuracy=",float(history.history['acc'][i-1]))
        print("loss=",float(history.history['loss'][i-1]))
else:
    for i in range(1, epochs + 1):
        log_metrics('accuracy', float(history.history['accuracy'][i-1]), i, i)
        log_metrics('loss', float(history.history['loss'][i-1]), i, i)
        print("accuracy=",float(history.history['accuracy'][i-1]))
        print("loss=",float(history.history['loss'][i-1]))

# Exporting model        
export_path = out_path
version = 0
if not tf.io.gfile.exists(export_path):
    tf.io.gfile.makedirs(export_path)
model_contents = tf.io.gfile.listdir(export_path)

saved_models = []
for mdir in model_contents:
    if mdir != 'logs' and mdir != 'metrics'and mdir != 'weights.h5':
        saved_models.append(int(mdir))
if len(saved_models) < 1:
    version = 1
else:
    version = max(saved_models) + 1
model.save(export_path + 'weights.h5')
tf.keras.backend.set_learning_phase(0)  # Ignore dropout at inference

if '1.1' in tf.__version__:
    with tf.keras.backend.get_session() as sess:
        tf.saved_model.simple_save(
            sess,
            export_path + str(version),
            inputs={'input': model.input},
            outputs={'output': model.output})
elif '2.' in tf.__version__:
    with tf.compat.v1.keras.backend.get_session() as sess:
        tf.compat.v1.saved_model.simple_save(
            sess,
            export_path + str(version),
            inputs={'input': model.input},
            outputs={'output': model.output})
print("Model saved, version = ", version)
