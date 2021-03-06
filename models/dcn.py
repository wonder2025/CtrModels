######################################################################
###  Please do not delete this info 
###  Author: Leo Shen
###  Email: szlemail@tom.com
###  Create Date 2018-10-05
###  Version v1.0
###  Last Modify Date 2018-10-05
###  Last Modify Author Leo Shen

import pandas as pd
import numpy as np
from sklearn.model_selection import StratifiedKFold
import tensorflow as tf
from sklearn.metrics import f1_score
import math
import os
import pickle

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
    
class DeepCrossNet():
    
    sess = None
    learning_rate_decay = 1
    learning_rate = None
    classed = None
    batch_size = None
    embed_dim_multiple = None
    n_cross_layers = None
    n_dnn_layers = None
    losses = []
    sparse_dim = None
    embed_dim = None
    dense_dim = None
    dnn_dim = None
    early_stop = None
    tol = None
    score = 0
    
    def __init__(self, batch_size = 64, classes = 11, learning_rate = 0.001,
                 learning_rate_decay = 0.95, embed_dim_multiple = 6, n_cross_layers = 6, n_dnn_layers = 6):
        self.batch_size = batch_size
        self.classes = classes
        self.learning_rate = learning_rate
        self.learning_rate_decay = learning_rate_decay
        self.embed_dim_multiple = embed_dim_multiple
        self.n_cross_layers = n_cross_layers
        self.n_dnn_layers = n_dnn_layers
        
        
        # input x should be 1 dim array. with is flattened
    def cross_layer(self, xn, x0):
        #weight
        stddev = 1/np.sqrt(self.sparse_dim + self.embed_dim)
        b = tf.Variable(tf.truncated_normal([self.embed_dim + self.dense_dim, 1], stddev = 1), name = 'b')
        w = tf.Variable(tf.truncated_normal([self.embed_dim + self.dense_dim, 1], stddev = stddev), name = 'w')
        wx0 = tf.expand_dims(x0, 2)
        wx = tf.expand_dims(xn, 2)
        dot = tf.matmul(wx0, tf.transpose(wx, [0,2,1]))
        x_out = tf.tensordot(dot, w, 1) + b + wx
        return tf.squeeze(x_out, 2)

    # input x should be 1 dim array. with is flattened
    def dnn(self, x0, nlayers = 3, outdim = 64, is_training = True):
          layer1 = tf.layers.dense(inputs = x0, units = 256, activation = tf.nn.relu, use_bias   = True)
          bn1 = tf.layers.batch_normalization(inputs = layer1, axis = -1, 
                              momentum   = 0.99,
                              epsilon    = 0.001,
                              center     = True,
                              scale      = True)
       
          layer2 = tf.layers.dense(inputs = bn1, units = outdim, activation = tf.nn.relu, use_bias   = True)
          bn2 = tf.layers.batch_normalization(inputs = layer2, axis = -1, 
                              momentum   = 0.99,
                              epsilon    = 0.001,
                              center     = True,
                              scale      = True)
          return bn2
        
    def buildGraph(self, xs, xd, y, lr, is_training = True):
        
        #embedding layer
        with tf.variable_scope("embed"):
            stddev = 1/np.sqrt(self.sparse_dim)
            w0 = tf.Variable(tf.truncated_normal([self.sparse_dim, self.embed_dim], stddev = stddev), name = 'w0')
            xe = tf.matmul(xs, w0, a_is_sparse = True)

        with tf.variable_scope("dcn"):
            x0 = tf.concat([xd, xe], axis = 1) 
            xdc = self.cross_layer(x0, x0)
            for i in range(self.n_cross_layers):
                xdc = self.cross_layer(xdc, x0)

            xdnn = self.dnn(x0, outdim = self.dnn_dim, nlayers = self.n_dnn_layers, is_training = is_training)
            x1 = tf.concat([xdc, xdnn], axis = 1) 

            stddev = 1/np.sqrt(self.embed_dim + self.dense_dim + self.dnn_dim)
            b1 = tf.Variable(tf.truncated_normal([self.classes], stddev = 1), name = 'b1')
            w1 = tf.Variable(tf.truncated_normal([self.embed_dim + self.dense_dim + self.dnn_dim, self.classes], stddev = stddev), name = 'w1')
            logits = tf.add(tf.matmul(x1, w1), b1)
            #logits = tf.squeeze(x_out, 1)
    
        y_out = tf.nn.softmax(logits)
        logloss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits_v2(logits = logits, labels = y))
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        with tf.control_dependencies(update_ops):
            optima = tf.train.AdamOptimizer(learning_rate = lr).minimize(logloss)

        return y_out, logloss, optima
        
    def earlyStop(self, eval_loss):
        self.losses.append(eval_loss)
        if len(self.losses) < self.tol + 1:
            return False
        else:
            return eval_loss > self.losses[-self.tol-1]
        
        
    def fit(self, X_sparse, X_dense, train_y, eval_set = None, early_stop = True, tolerance = 5, max_batches = 2000, eval_batches = 1):
        #params
        self.sparse_dim = X_sparse.shape[1]
        self.embed_dim = self.embed_dim_multiple * round(math.pow(self.sparse_dim, 0.5))
        self.dense_dim = X_dense.shape[1]
        self.dnn_dim = 1024
        self.early_stop = early_stop
        self.tol = tolerance
        self.losses = []
        
        #placeholder
        xs = tf.placeholder(tf.float32, shape = [None, self.sparse_dim], name = 'xs')
        xd = tf.placeholder(tf.float32, shape = [None, self.dense_dim], name = 'xd')
        y = tf.placeholder(tf.float32, shape = [None, self.classes], name = 'y')
        lr = tf.placeholder(tf.float32, name = 'lr')
        is_training = tf.placeholder(tf.bool, name = 'is_bn_trainable')

        y_out, logloss, optima = self.buildGraph(xs, xd, y, lr, is_training)
        if self.sess != None:
            self.sess.close()
        self.sess = tf.Session()
        sess = self.sess
        print("start Train session dense_dim: %d sparse_dim:%d embed_dim:%d ... "%(self.dense_dim, self.sparse_dim, self.embed_dim))
        sess.run(tf.global_variables_initializer())
        samples = len(X_sparse)
        batches = samples // self.batch_size + 1
        cur_lr = self.learning_rate
        for i in range(max_batches):
            for batch in range(batches):
                start = batch * self.batch_size
                end = min((batch + 1) * self.batch_size, samples)
                xs_batch = X_sparse[start:end]
                xd_batch = X_dense[start:end]
                sess.run(optima, feed_dict = {xs:xs_batch, xd:xd_batch, y:train_y[start:end], lr:cur_lr,  is_training:True})

            cur_lr = cur_lr * self.learning_rate_decay
            train_loss = sess.run(logloss, feed_dict = {xs:X_sparse[:1024], xd:X_dense[:1024], y:train_y[:1024], is_training:False})
            if eval_set != None:
                eval_loss = sess.run(logloss, feed_dict = {xs:eval_set[0][:1024], xd:eval_set[1][:1024],
                                                           y:eval_set[2][:1024], is_training:False})
                print("train_loss:%f eval_loss:%f"%(train_loss, eval_loss))
                
            else:
                print("train_loss:%f"%(train_loss))
                
            if eval_set != None and i%eval_batches == 0:
                eval_len = eval_set[0].shape[0]
                sum_score = 0
                num_score = 0
                for index in range(0, eval_len, 4096):
                    end = min(index + 4096, eval_len)
                    pred = sess.run(y_out, feed_dict = {xs:eval_set[0][index:end],
                                                        xd:eval_set[1][index:end],
                                                        y:eval_set[2][index:end],
                                                        is_training:False})
                    pred_label = np.argmax(pred, axis = 1)
                    true_label = np.argmax(np.array(eval_set[2][index:end]), axis = 1)
                    score = np.square(f1_score(true_label, pred_label, average = 'macro'))
                    sum_score = sum_score + score
                    num_score = num_score + 1
                if num_score > 0:
                    print("f1-score:",sum_score/num_score)
                    self.score = sum_score/num_score
                    if self.earlyStop(self.score):
                        break
            
        self.sess = sess
        self.xs = xs
        self.xd = xd
        self.y_out = y_out
        
        
    def predict(self, X_sparse, X_dense):
        pred = self.sess.run(self.y_out, feed_dict = {self.xs:X_sparse, self.xd:X_dense})
        return pred

    def __del__(self):
        if self.sess != None:
            self.sess.close()



    
# example 
#import data:
def savePickle(target, filename):
    with open(filename, "wb") as f:
        pickle.dump(target, f)
        
def loadPickle(filename):
    with open(filename, "rb") as f:
        return pickle.load(f)
    
train_x_continuous = np.array(loadPickle("../data/normaldata/train_x_continuous.pkl"))
train_x_onehot = np.array(loadPickle("../data/normaldata/train_x_onehot.pkl"))
test_x_continous = np.array(loadPickle("../data/normaldata/test_x_continous.pkl"))
test_x_onehot = np.array(loadPickle("../data/normaldata/test_x_onehot.pkl"))
train_y = np.array(loadPickle("../data/normaldata/train_y.pkl"))
label_dict = loadPickle("../data/normaldata/label_dict.pkl")
labelTestResult = loadPickle("../data/normaldata/TestResult.pkl")
print("data loading finished!")
with open("dcn.log", "w+") as f:
    f.writelines("start dcn\n")
    
skf = StratifiedKFold(n_splits=10, random_state = 2018)

for lr in [0.001]:
    for deeplayers in [3,2]:
        for crosslayers in [4,5,6]:
            scores = []
            
            
            for train_index, test_index in skf.split(train_x_continuous, np.argmax(train_y, axis = 1)):
                dcn = DeepCrossNet(batch_size = 64, classes = 11, learning_rate = lr,
                             learning_rate_decay = 0.9, embed_dim_multiple = 5,
                             n_cross_layers = crosslayers, n_dnn_layers = deeplayers)
                edata = (train_x_onehot[test_index], train_x_continuous[test_index], train_y[test_index])
                dcn.fit(train_x_onehot[train_index], train_x_continuous[train_index], train_y[train_index], 
                        eval_set = edata, early_stop = True, tolerance = 200, max_batches = 1000, eval_batches = 5)
                scores.append(dcn.score)
                del dcn
                break
            print("lr:%f, deeplayer:%d, crosslayser:%d score:%.4f\n"%(lr, deeplayers, crosslayers, np.mean(scores)))
            with open("dcn.log", "a+") as f:
                f.writelines("lr:%f, deeplayer:%d, crosslayser:%d score:%.4f\n"%(lr, deeplayers, crosslayers, np.mean(scores)))
            print(scores)
                
                
# pred = dcn.predict(test_x_onehot, test_x_continous)
# pred_label = np.argmax(pred, axis = 1)
# pred_label = [label_dict[i] for i in pred_label]
# labelTestResult['predict'] = pred_label
# labelTestResult.to_csv("./result/dcn20181006.csv", index = None)

