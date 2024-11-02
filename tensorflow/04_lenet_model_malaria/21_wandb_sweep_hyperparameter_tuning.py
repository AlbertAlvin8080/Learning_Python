# -*- coding: utf-8 -*-
"""21_wandb_sweep_hyperparameter_tuning.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1LGcJUdtlmPangy95MwwsXO7Bk1-uctj1
"""

# https://www.tensorflow.org/datasets/api_docs/python/tfds/load
# https://www.tensorflow.org/datasets/catalog/malaria?hl=pt-br

import cv2 as cv
import albumentations as A
import os
import sys
import datetime
import io

import tensorflow as tf
import tensorflow_datasets as tfds
from tensorflow.keras.layers import (
    Conv2D,
    MaxPool2D,
    Dense,
    Flatten,
    Input,
    BatchNormalization,
    Layer,
    Dropout,
    Resizing,
    Rescaling,
    RandomFlip,
    RandomRotation,
)
from tensorflow.keras.losses import BinaryCrossentropy
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.models import Model
from tensorflow.keras.metrics import (
    BinaryAccuracy,
    FalsePositives,
    FalseNegatives,
    TruePositives,
    Accuracy,
    TrueNegatives,
    AUC,
    Precision,
    Recall,
)
from tensorflow.keras.callbacks import (
    Callback,
    CSVLogger,
    EarlyStopping,
    LearningRateScheduler,
    ModelCheckpoint,
    ReduceLROnPlateau,
)
from tensorflow.keras.regularizers import L2, L1
import tensorflow_probability as tfp
from tensorboard.plugins.hparams import api as hp

import math
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import sklearn
from sklearn.metrics import confusion_matrix, roc_curve

# NOTE: for running locally
dataset, dataset_info = tfds.load(
    "malaria",
    with_info=True,
    as_supervised=True,
    shuffle_files=True,
    split=["train"],
    # This dataset in particular has not been splitted previously for us.
    # split=["train", "test"]
)

# from google.colab import drive

# drive.mount('/content/drive')

# data_dir = '/content/drive/MyDrive/tfds_data/'

# # Load the dataset and specify data_dir to save it in Google Drive
# dataset, dataset_info = tfds.load(
#     "malaria",
#     with_info=True,
#     as_supervised=True,
#     shuffle_files=True,
#     split=["train"],
#     data_dir=data_dir,  # Use Google Drive for storage
# )

print(dataset)
# print(dataset_info)


def split_dataset(
    dataset: tf.data.Dataset, train_ratio: float, val_ratio: float, test_ratio: float
) -> tuple[tf.data.Dataset, tf.data.Dataset, tf.data.Dataset]:
    size = len(dataset)
    train_dataset = dataset.take(int(size * train_ratio))
    val_dataset = dataset.skip(int(size * train_ratio)).take(int(size * val_ratio))
    test_dataset = dataset.skip(int(size * (train_ratio + val_ratio)))

    return train_dataset, val_dataset, test_dataset


def plot_img(dataset: tf.data.Dataset):
    rows = 4
    cols = 4
    plt.figure(figsize=[5, 6])
    for i, (image, label) in enumerate(dataset):
        # print(image[112,112])
        if len(image.shape) <= 3:
            plt.subplot(rows, cols, i + 1)
            plt.imshow(image)
            plt.axis("off")
            plt.title(dataset_info.features["label"].int2str(label))
        else:
            for j in range(image.shape[0]):
                if j > rows * cols - 1:
                    break
                plt.subplot(rows, cols, j + 1)
                plt.imshow(image[j])
                plt.axis("off")
                plt.title(dataset_info.features["label"].int2str(label[j].numpy()))
    plt.show()


IMG_SIZE = 224


# passing the label because tf.data.Dataset.map() passes it as well.
def resize_and_normalize(image, label):
    # divinding by 255.0 element wise.
    new_img = tf.image.resize(image, (IMG_SIZE, IMG_SIZE)) / 255.0
    return new_img, label


# train_dataset, val_dataset, test_dataset = split_dataset(dataset[0], 0.8, 0.1, 0.1)

# train_dataset = (
#     train_dataset.map(resize_and_normalize)
#     .shuffle(buffer_size=8, reshuffle_each_iteration=True)
#     .batch(32)
#     .prefetch(tf.data.AUTOTUNE)
# )

# val_dataset = (
#     val_dataset.map(resize_and_normalize)
#     .shuffle(buffer_size=8, reshuffle_each_iteration=True)
#     .batch(32)
#     .prefetch(tf.data.AUTOTUNE)
# )

# # It's useless to shuffle and prefetch the test_dataset because it's not used for training.
# # It's still necessary to batch it since the model expects the inputs to be in batches though.
# test_dataset = test_dataset.map(resize_and_normalize).batch(1)

#####################################################################################################

# !pip install wandb
# !wandb login
import wandb

# NOTE: WandbCallback is deprecated
# from wandb.keras import WandbCallback
from wandb.integration.keras import (
    WandbMetricsLogger,
    WandbModelCheckpoint,
    WandbEvalCallback,
)

CONFIG = {
    "input_shape": (IMG_SIZE, IMG_SIZE, 3),
    "filters_1": 6,
    "filters_2": 16,
    "kernel_size": 3,
    "activation_1": "relu",
    "activation_2": "sigmoid",
    "dropout": 0.01,
    "regularization_l2": 0.1,
    "optimizer": "adam",
    "loss": "binary_crossentropy",
    "pool_size": 2,
    "strides_1": 1,
    "strides_2": 2,
    "dense_1": 32,
    "dense_2": 32,
    "dense_out": 1,
    "learning_rate": 0.01,
    "batch_size": 32,
    "epochs": 8,
    # "epochs": 1,
}

###
train_dataset, val_dataset, test_dataset = split_dataset(dataset[0], 0.8, 0.1, 0.1)

train_dataset = (
    train_dataset.map(resize_and_normalize)
    .shuffle(buffer_size=8, reshuffle_each_iteration=True)
    .batch(CONFIG["batch_size"])
    .prefetch(tf.data.AUTOTUNE)
)

val_dataset = (
    val_dataset.map(resize_and_normalize)
    .shuffle(buffer_size=8, reshuffle_each_iteration=False)
    .batch(CONFIG["batch_size"])
    .prefetch(tf.data.AUTOTUNE)
)

test_dataset = test_dataset.map(resize_and_normalize).batch(1)
###


def hyperparam_tuning(config):
    model = tf.keras.Sequential(
        [
            Input(shape=config["input_shape"]),
            Conv2D(
                filters=config["filters_1"],
                kernel_size=config["kernel_size"],
                strides=config["strides_1"],
                padding="valid",
                activation=config["activation_1"],
                kernel_regularizer=L2(config["regularization_l2"]),
            ),
            BatchNormalization(),
            MaxPool2D(pool_size=config["pool_size"], strides=config["strides_2"]),
            Dropout(rate=config["dropout"]),
            Conv2D(
                filters=config["filters_2"],
                kernel_size=config["kernel_size"],
                strides=config["strides_1"],
                padding="valid",
                activation=config["activation_1"],
                kernel_regularizer=L2(config["regularization_l2"]),
            ),
            BatchNormalization(),
            MaxPool2D(pool_size=config["pool_size"], strides=config["strides_2"]),
            Flatten(),
            Dense(
                config["dense_1"],
                activation=config["activation_1"],
                kernel_regularizer=L2(config["regularization_l2"]),
            ),
            BatchNormalization(),
            Dropout(rate=config["dropout"]),
            Dense(
                config["dense_2"],
                activation=config["activation_1"],
                kernel_regularizer=L2(config["regularization_l2"]),
            ),
            BatchNormalization(),
            Dense(1, activation=config["activation_2"]),
        ]
    )

    return model


###

sweep_config = {
    "entity": "albertalvin8080",
    "name": "Malaria-Detection-Sweep",
    "project": "Malaria-Detection-Sweep",
    "method": "random",
    "metric": {
        # "name": "accuracy",
        "name": "epoch/accuracy",
        "goal": "maximize",
    },
    "parameters": {
        "dense_1": {"values": [16, 32, 64, 128]},
        "dense_2": {"values": [16, 32, 64, 128]},
        "dropout": {
            "min": 0.1,
            "max": 0.4,
        },
        "learning_rate": {
            "min": 0.001,
            "max": 0.1,
        },
        "regularization_l2": {
            "distribution": "uniform",
            "min": 1e-4,
            "max": 1e-2,
        },
    },
}

sweep_id = wandb.sweep(sweep_config)


def train():
    #  `project=` and `entity=` are put inside the sweep_config.
    #   with wandb.init(project="Malaria-Detection", entity="albertalvin8080", config=CONFIG):
    with wandb.init(config=CONFIG):
        config = wandb.config
        model = hyperparam_tuning(config)
        model.compile(
            optimizer=Adam(learning_rate=config["learning_rate"]),
            loss="binary_crossentropy",
            metrics=[
                # "accuracy"
                BinaryAccuracy(name="accuracy"),
                FalsePositives(name="fp"),
                FalseNegatives(name="fn"),
                TruePositives(name="tp"),
                TrueNegatives(name="tn"),
                AUC(name="auc"),
                Precision(name="precision"),
                Recall(name="recall"),
            ],
        )
        model.fit(
            train_dataset.take(10),
            epochs=config.epochs,
            verbose=2,
            callbacks=[WandbMetricsLogger()],
        )


runs_count = 5
wandb.agent(sweep_id, function=train, count=runs_count)

# wandb.finish()

# !pip install wandb
# !wandb login
