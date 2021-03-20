import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
import matplotlib.pyplot as plt
from tensorflow.keras.callbacks import TensorBoard
from tensorflow.keras.utils import to_categorical
from datetime import datetime
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
import random

# import simulated galaxies

with open('inputgalaxies.npy','rb') as f:

  gal_input = np.load(f)
  
  z_input = np.load(f)
  
with open('targetgalaxies.npy','rb') as g:

  gal_target = np.load(g)
  
  z_target = np.load(g)

conditional = 'no'

z_inputs = len(gal_input)*[z_input]
z_targets = len(gal_target)*[z_target]

redshifts = np.transpose([z_inputs, z_targets]) # combine redshifts into 1 array

# shuffle and then split galaxy and redshift data into test and train sets
gal_input_train, gal_input_test, gal_target_train, gal_target_test, redshifts_train, redshifts_test \
    = train_test_split(gal_input, gal_target, redshifts, test_size=0.2, shuffle=True)

n_input_train, w, h, c = gal_input_train.shape
n_input_test, _, _, _ = gal_input_test.shape

z_labels = redshifts_test

z_condition = 2

# create a sampling layer

class Sampling(layers.Layer):
    """Uses (z_mean, z_log_var) to sample z, the vector encoding a digit."""

    def call(self, inputs):
        z_mean, z_log_var = inputs
        batch = tf.shape(z_mean)[0]
        dim = tf.shape(z_mean)[1]
        epsilon = tf.keras.backend.random_normal(shape=(batch, dim))
        return z_mean + tf.exp(0.5 * z_log_var) * epsilon
    
# build the encoder

latent_dim = 5

encoder_inputs = keras.Input(shape=(w, h, c))
# We need another input for the labels.
# If our condition were a continuous quantity, this could just be
# that value, but here we have a set of categorical classes:
condition_inputs = keras.Input(shape=(z_condition,))
x = layers.Conv2D(32, 3, activation="relu", strides=2, padding="same")(encoder_inputs)
x = layers.Conv2D(64, 3, activation="relu", strides=2, padding="same")(x)
x = layers.Conv2D(128, 3, activation="relu", strides=2, padding="same")(x)
x = layers.Flatten()(x)
# I suggest we try including the conditions here. This means they can
# be processed (by a couple of fully-connected layers and one
# non-linearity) in producing the latent encoding, but avoids some
# complications of adding them in earlier. This is ok, because the
# basic features that the network needs to learn should not depend
# very strongly on the labels, but including them here should allow
# our encoding to be more efficient representation of each class.
if conditional=='yes':
    x = layers.Concatenate()([x, condition_inputs])
    x = layers.Dense(16, activation="relu")(x)
    z_mean = layers.Dense(latent_dim, name="z_mean")(x)
    z_log_var = layers.Dense(latent_dim, name="z_log_var")(x)
    z = Sampling()([z_mean, z_log_var])
    encoder = keras.Model([encoder_inputs, condition_inputs], [z_mean, z_log_var, z], name="encoder")
else:
    x = layers.Dense(16, activation="relu")(x)
    z_mean = layers.Dense(latent_dim, name="z_mean")(x)
    z_log_var = layers.Dense(latent_dim, name="z_log_var")(x)
    z = Sampling()([z_mean, z_log_var])
    encoder = keras.Model(encoder_inputs, [z_mean, z_log_var, z], name="encoder")
encoder.summary()    

# build the decoder

latent_inputs = keras.Input(shape=(latent_dim,))
# We add our conditions again here. One might think this is
# unnecessary, as the latent encoding already contains this
# information. However, I think including them here has two
# advantages: (1) it means that the latent encoding does not need to
# contain the condition, so can be more efficient, and (2) if we use
# the decoder alone, we can specify the condition.
if conditional=='yes':
    x = layers.Concatenate()([latent_inputs, condition_inputs])
    x = layers.Dense(7 * 7 * 64, activation="relu")(x)
else:
    x = layers.Dense(7 * 7 * 64, activation="relu")(latent_inputs)
x = layers.Reshape((7, 7, 64))(x)
x = layers.Conv2DTranspose(64, 3, activation="relu", strides=2, padding="valid")(x)
x = layers.Conv2DTranspose(32, 3, activation="relu", strides=2, padding="same")(x)
x = layers.Conv2DTranspose(32, 3, activation="relu", strides=2, padding="same")(x)
decoder_outputs = layers.Conv2DTranspose(c, 3, activation="sigmoid", padding="same")(x)
if conditional=='yes':
    decoder = keras.Model([latent_inputs, condition_inputs], decoder_outputs, name="decoder")
else:
    decoder = keras.Model(latent_inputs, decoder_outputs, name="decoder")
decoder.summary()

# define the VAE model

def reconstruction_loss(targets, outputs):
    loss = keras.losses.mean_squared_error(outputs, targets)
    loss = tf.reduce_mean(tf.reduce_sum(loss, axis=(1, 2)))
    return loss

beta = 0.1
kl_loss = -0.5 * (1 + z_log_var - tf.square(z_mean) - tf.exp(z_log_var))
kl_loss = beta * tf.reduce_mean(tf.reduce_sum(kl_loss, axis=1))

if conditional=='yes':
    vae_outputs = decoder([encoder([encoder_inputs, condition_inputs])[-1],
                           condition_inputs])
    vae = keras.Model([encoder_inputs, condition_inputs], vae_outputs)
else:
    vae_outputs = decoder(encoder(encoder_inputs)[-1])
    vae = keras.Model(encoder_inputs, vae_outputs)
vae.add_loss(kl_loss)
vae.add_metric(kl_loss, name='kl_loss')

vae.compile(optimizer=keras.optimizers.Adam(), loss=reconstruction_loss,
            metrics=[reconstruction_loss])

# train the VAE

# This callback will stop the training when there is no improvement in
# the validation loss for three consecutive epochs
early_stopping_callback = tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=15)

epochs = 100
batch_size = 128

logdir = "/tmp/tb/" + datetime.now().strftime("%Y%m%d-%H%M%S")
tensorboard_callback = keras.callbacks.TensorBoard(log_dir=logdir)

if conditional=='yes':
    history = vae.fit([gal_input_train, redshifts_train], gal_target_train,
                      epochs=epochs,
                      batch_size=batch_size,
                      shuffle=True,
                      validation_data=([gal_input_test, redshifts_test], gal_target_test),
                      callbacks=[tensorboard_callback, early_stopping_callback])
    
    reconstructions = vae.predict([gal_input_test, redshifts_test])
    z_mean, z_log_var, z = encoder.predict([gal_input_test, redshifts_test])
else:
    history = vae.fit(gal_input_train, gal_target_train,
                      epochs=epochs,
                      batch_size=batch_size,
                      shuffle=True,
                      validation_data=(gal_input_test, gal_target_test),
                      callbacks=[tensorboard_callback, early_stopping_callback])
    
    reconstructions = vae.predict(gal_input_test)
    z_mean, z_log_var, z = encoder.predict(gal_input_test)


vae.save('Galaxy_Model') # Save model for future use

# summarize history for loss

plt.plot(history.history['loss'],'b')
plt.plot(history.history['val_loss'],'r')
plt.title('Model Loss')
plt.ylabel('loss')
plt.xlabel('epoch')
plt.legend(['Training', 'Validation'], loc='upper right')
plt.savefig('model_loss.pdf')

# show what the original, simulated and reconstructed galaxies look like

n = 17 # number of filters
m = gal_target_test.shape[0]
r = random.randint(0,m-1) # choosing a random galaxy to plot (as input and target redshift)
fig, axarr = plt.subplots(3, n, figsize=(30, 6))
for i, ax in enumerate(axarr[0]):
    ax.imshow(gal_target_test[r,:,:,i], cmap='inferno',
               origin='lower', interpolation='nearest',
               vmin=0, vmax=1)
for i, ax in enumerate(axarr[1]):
    ax.imshow(gal_input_test[r,:,:,i], cmap='inferno',
               origin='lower', interpolation='nearest',
               vmin=0, vmax=1)
for i, ax in enumerate(axarr[2]):
    ax.imshow(reconstructions[r,:,:,i], cmap='inferno',
               origin='lower', interpolation='nearest',
               vmin=0, vmax=1)
for ax in axarr.flat:
    ax.axis('off')
plt.suptitle('Galaxy image ' + str(r) + ' with input z = ' + str(np.round(redshifts[0,0],2)) \
             + ' and target z = ' + str(np.round(redshifts[0,1],2)))
plt.savefig('examples.pdf')

# display a 2D plot of redshifting condition in the latent space

fig, axarr = plt.subplots(figsize=(6, 6))
plt.scatter(z[:, 0], z[:, 1], c=z_labels, marker='.')
plt.axis('square')
plt.colorbar()
plt.title('Digit Classes in Latent Space')
plt.xlabel('z[0]')
plt.ylabel('z[1]')
plt.savefig('latent_scatter.pdf')
