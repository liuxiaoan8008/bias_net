import os.path
import time
from models import alexnet
import tensorflow as tf
import train_util as tu
import threading


def train(
        epochs,
        batch_size,
        learning_rate,
        dropout,
        momentum,
        lmbda,
        resume,
        display_step,
        test_step,
        ckpt_path,
        summary_path
):

    train_img_path = '/var/data/bias_data/image/train'
    evaluate_path = '/var/data/bias_data/image/train'
    num_whole_images = 60000
    num_batches = int(float(num_whole_images) / batch_size)
    wnid_labels = ['cheer_out', 'fearful_out', 'happy_out', 'joy_out', 'rage_out', 'sorrow_out']

    x = tf.placeholder(tf.float32, [None, 150, 150, 3])
    y = tf.placeholder(tf.float32, [None, 6])

    lr = tf.placeholder(tf.float32)
    keep_prob = tf.placeholder(tf.float32)

    # queue of examples being filled on the cpu
    with tf.device('/cpu:0'):
        q = tf.FIFOQueue(batch_size * 3, [tf.float32, tf.float32], shapes=[[150, 150, 3], [6]])
        enqueue_op = q.enqueue_many([x, y])
        x_b, y_b = q.dequeue_many(batch_size)

    pred, prob = alexnet.classifier(x_b, keep_prob)

    # cross-entropy and weight decay
    with tf.name_scope('cross_entropy'):
        cross_entropy = tf.reduce_mean(
            tf.nn.softmax_cross_entropy_with_logits(logits=pred, labels=y_b, name='cross-entropy'))

    with tf.name_scope('l2_loss'):
        l2_loss = tf.reduce_sum(lmbda * tf.stack([tf.nn.l2_loss(v) for v in tf.get_collection('weights')]))
        tf.summary.scalar('l2_loss', l2_loss)

    with tf.name_scope('loss'):
        loss = cross_entropy + l2_loss
        tf.summary.scalar('loss', loss)

    # accuracy
    with tf.name_scope('accuracy'):
        correct = tf.equal(tf.argmax(pred, 1), tf.argmax(y_b, 1))
        accuracy = tf.reduce_mean(tf.cast(correct, tf.float32))
        tf.summary.scalar('accuracy', accuracy)

    global_step = tf.Variable(0, trainable=False)
    epoch = tf.div(global_step, num_batches)

    # momentum optimizer
    with tf.name_scope('optimizer'):
        optimizer = tf.train.MomentumOptimizer(learning_rate=lr, momentum=momentum).minimize(loss,
                                                                                             global_step=global_step)
    merged = tf.summary.merge_all()
    saver = tf.train.Saver()

    coord = tf.train.Coordinator()
    init = tf.global_variables_initializer()

    with tf.Session(config=tf.ConfigProto()) as sess:
        if resume:
            saver.restore(sess, os.path.join(ckpt_path, 'alexnet-cnn.ckpt'))
        else:
            sess.run(init)

        # enqueuing batches procedure
        def enqueue_batches():
            while not coord.should_stop():
                im, l = tu.read_batch(batch_size, train_img_path, wnid_labels)
                sess.run(enqueue_op, feed_dict={x: im, y: l})

        # creating and starting parallel threads to fill the queue
        num_threads = 3
        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=enqueue_batches)
            t.setDaemon(True)
            t.start()
            threads.append(t)

        # operation to write logs for tensorboard visualization
        train_writer = tf.summary.FileWriter(os.path.join(summary_path, 'train'), sess.graph)

        valid_batch_size = 126
        val_im, val_cls = tu.read_batch(valid_batch_size, evaluate_path, wnid_labels)

        start_time = time.time()
        for e in range(sess.run(epoch), epochs):
            for i in range(num_batches):

                _, step = sess.run([optimizer, global_step], feed_dict={lr: learning_rate, keep_prob: dropout})
                # train_writer.add_summary(summary, step)

                # decaying learning rate
                if step == 170000 or step == 350000:
                    learning_rate /= 10

                # display current training informations
                if step % display_step == 0:
                    c, a = sess.run([loss, accuracy], feed_dict={lr: learning_rate, keep_prob: 1.0})
                    print (
                        'Epoch: {:03d} Step/Batch: {:09d} --- Loss: {:.7f} Training accuracy: {:.4f}'.format(e, step, c,
                                                                                                             a))

                # make test and evaluate validation accuracy
                if step % test_step == 0:
                    v_a = sess.run(accuracy, feed_dict={x_b: val_im, y_b: val_cls, lr: learning_rate, keep_prob: 1.0})
                    # intermediate time
                    int_time = time.time()
                    print ('Elapsed time: {}'.format(tu.format_time(int_time - start_time)))
                    print ('Validation accuracy: {:.04f}'.format(v_a))
                    # save weights to file
                    save_path = saver.save(sess, os.path.join(ckpt_path, 'alexnet-cnn.ckpt'))
                    print('Variables saved in file: %s' % save_path)

        end_time = time.time()
        print ('Elapsed time: {}'.format(tu.format_time(end_time - start_time)))
        save_path = saver.save(sess, os.path.join(ckpt_path, 'alexnet-cnn.ckpt'))
        print('Variables saved in file: %s' % save_path)

        coord.request_stop()
        coord.join(threads)


def predict(keep_prob, prob, sess, x_holder, x):

    feed_dict = {
        x_holder: x,
        keep_prob: 1.0
    }

    predictions = sess.run(prob,feed_dict=feed_dict)
    return predictions


def preload():
    ckpt_path = 'ckpt-alexnet'
    x_holder = tf.placeholder(tf.float32, [None, 150, 150, 3])
    keep_prob = tf.placeholder(tf.float32)
    pred, prob = alexnet.classifier(x_holder, keep_prob)
    sess = tf.Session()
    saver = tf.train.Saver()
    saver.restore(sess, os.path.join(ckpt_path, 'alexnet-cnn.ckpt'))
    return keep_prob, prob, sess, x_holder


if __name__ == '__main__':
    test_images = []
    test_label = []

    test_images = test_images + tu.read_test_image('/var/data/bias_data/image/test/test_old')
    test_images = test_images + tu.read_test_image('/var/data/bias_data/image/test/test_young')

    for i in range(len(test_images)):
        if i < (len(test_label)/2):
            test_label.append(1) # old
        else:
            test_label.append(0) # young

    keep_prob, prob, sess, x_holder = preload()

    results = predict(keep_prob, prob, sess, x_holder,test_images)

    results_two_class = []
    for re in results:
        results_two_class.append([sum([re[0],re[2],re[3]]),sum([re[1],re[4],re[5]])])

    re_file_two = open('/var/data/bias_data/image/test/test_results_two.txt','w')
    for re,label in zip(results_two_class,test_label):
        print re
        re_file_two.write(label+','+str(re[0])+','+str(re[1])+'\n')
    re_file_two.close()

    re_file_six = open('/var/data/bias_data/image/test/test_results_six.txt','w')
    for re,label in zip(results,test_label):
        six = ','.join(re)
        re_file_six.write(label+','+six+'\n')
    re_file_six.close()





    # DROPOUT = 0.5
    # MOMENTUM = 0.9
    # LAMBDA = 5e-04  # for weight decay
    # LEARNING_RATE = 1e-03
    # EPOCHS = 90
    # BATCH_SIZE = 126
    # DISPLAY_STEP = 10
    # TEST_STEP = 500
    # resume = False
    #
    # CKPT_PATH = 'ckpt-alexnet'
    # if not os.path.exists(CKPT_PATH):
    #     os.makedirs(CKPT_PATH)
    # SUMMARY = 'summary'
    # if not os.path.exists(SUMMARY):
    #     os.makedirs(SUMMARY)
    #
    # train(
    #     EPOCHS,
    #     BATCH_SIZE,
    #     LEARNING_RATE,
    #     DROPOUT,
    #     MOMENTUM,
    #     LAMBDA,
    #     resume,
    #     DISPLAY_STEP,
    #     TEST_STEP,
    #     CKPT_PATH,
    #     SUMMARY,
    # )
