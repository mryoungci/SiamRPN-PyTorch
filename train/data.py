# -*- coding: utf-8 -*-
import os
import sys
import cv2
import time
import torch
import random
import numpy as np
import os.path as osp
from util import util
from config import config
from torch.utils.data import Dataset
from got10k.datasets import ImageNetVID, GOT10k
from torchvision import datasets, transforms, utils
from got10k.datasets import ImageNetVID, GOT10k
from custom_transforms import Normalize, ToTensor, RandomStretch, \
    RandomCrop, CenterCrop, RandomBlur, ColorAug

class TrainDataLoader(Dataset):
    def __init__(self, seq_dataset, name = 'GOT-10k'):

        self.max_inter        = config.max_inter
        self.sub_class_dir    = seq_dataset
        self.ret              = {}
        self.count            = 0
        self.name             = name
        self.anchors          = util.generate_anchors(  config.total_stride,
                                                        config.anchor_base_size,
                                                        config.anchor_scales,
                                                        config.anchor_ratios,
                                                        config.anchor_valid_scope) #centor

    def get_transform_for_train(self):
        transform_list = []
        transform_list.append(transforms.ToTensor())
        transform_list.append(transforms.Normalize(mean=(0.5,0.5,0.5), std=(0.5,0.5,0.5)))
        return transforms.Compose(transform_list)


    def _pick_img_pairs(self, index_of_subclass):

        assert index_of_subclass < len(self.sub_class_dir), 'index_of_subclass should less than total classes'

        video_name = self.sub_class_dir[index_of_subclass][0]
        video_num  = len(video_name)
        video_gt = self.sub_class_dir[index_of_subclass][1]
        #print('video_num', video_num)

        status = True
        while status:
            if self.max_inter >= video_num-1:
                self.max_inter = video_num//2

            template_index = np.clip(random.choice(range(0, max(1, video_num - self.max_inter))), 0, video_num-1)

            detection_index= np.clip(random.choice(range(1, max(2, self.max_inter))) + template_index, 0, video_num-1)

            template_img_path, detection_img_path  = video_name[template_index], video_name[detection_index]

            template_gt  = video_gt[template_index]

            detection_gt = video_gt[detection_index]

            if template_gt[2]*template_gt[3]*detection_gt[2]*detection_gt[3] != 0:
                status = False
            else:
                print('Warning : Encounter object missing, reinitializing ...')

        # load infomation of template and detection
        self.ret['template_img_path']      = template_img_path
        self.ret['detection_img_path']     = detection_img_path
        self.ret['template_target_x1y1wh'] = template_gt
        self.ret['detection_target_x1y1wh']= detection_gt
        t1, t2 = self.ret['template_target_x1y1wh'].copy(), self.ret['detection_target_x1y1wh'].copy()
        self.ret['template_target_xywh']   = np.array([t1[0]+t1[2]//2, t1[1]+t1[3]//2, t1[2], t1[3]], np.float32)
        self.ret['detection_target_xywh']  = np.array([t2[0]+t2[2]//2, t2[1]+t2[3]//2, t2[2], t2[3]], np.float32)
        self.ret['anchors'] = self.anchors
        #self._average()

    def open(self):

        '''template'''
        template_img = cv2.imread(self.ret['template_img_path'])

        img_mean = np.mean(template_img, axis=(0, 1))

        exemplar_img, scale_z, s_z, w_x, h_x = self.get_exemplar_image(   template_img,
                                                                self.ret['template_target_xywh'],
                                                                config.template_img_size,
                                                                config.context, img_mean )

        size_x = config.template_img_size
        x1, y1 = int((size_x + 1) / 2 - w_x / 2), int((size_x + 1) / 2 - h_x / 2)
        x2, y2 = int((size_x + 1) / 2 + w_x / 2), int((size_x + 1) / 2 + h_x / 2)
        #frame = cv2.rectangle(exemplar_img, (x1,y1), (x2,y2), (0, 255, 0), 1)
        #cv2.imwrite('exemplar_img.png',frame)
        #cv2.waitKey(0)

        self.ret['exemplar_img'] = exemplar_img

        '''detection'''
        detection_img = cv2.imread(self.ret['detection_img_path'])
        d = self.ret['detection_target_xywh']

        cx, cy, w, h = d  # float type

        wc_z = w + 0.5 * (w + h)
        hc_z = h + 0.5 * (w + h)
        s_z = np.sqrt(wc_z * hc_z)

        s_x = s_z / 135

        img_mean_d = tuple(map(int, detection_img.mean(axis=(0, 1))))

        a_x = np.random.choice(range(-30,30))
        a_x = a_x * s_x
        b_y = np.random.choice(range(-30,30))
        b_y = b_y * s_x

        instance_img, w_x, h_x, scale_x = self.get_instance_image(  detection_img, d,
                                                                    config.template_img_size,
                                                                    config.detection_img_size,
                                                                    config.context,
                                                                    a_x, b_y,
                                                                    img_mean_d )

        size_x = config.detection_img_size

        x1, y1 = int((size_x + 1) / 2 - w_x / 2), int((size_x + 1) / 2 - h_x / 2)
        x2, y2 = int((size_x + 1) / 2 + w_x / 2), int((size_x + 1) / 2 + h_x / 2)

        #frame_d = cv2.rectangle(instance_img, (int(x1-(a_x*scale_x)),int(y1-(b_y*scale_x))), (int(x2-(a_x*scale_x)),int(y2-(b_y*scale_x))), (0, 255, 0), 2)
        #cv2.imwrite('detection_img.png',frame_d)

        w  = x2 - x1
        h  = y2 - y1
        cx = x1 + w/2
        cy = y1 + h/2

        im_h, im_w, _ = instance_img.shape
        cy_o = (im_h - 1) / 2
        cx_o = (im_w - 1) / 2
        cy = cy_o + np.random.randint(- config.max_translate, config.max_translate + 1)
        cx = cx_o + np.random.randint(- config.max_translate, config.max_translate + 1)
        gt_cx = cx_o - cx
        gt_cy = cy_o - cy

        self.ret['instance_img'] = instance_img
        self.ret['cx, cy, w, h'] = [a_x, b_y, w, h]


    def get_exemplar_image(self, img, bbox, size_z, context_amount, img_mean=None):
        cx, cy, w, h = bbox

        wc_z = w + context_amount * (w + h)
        hc_z = h + context_amount * (w + h)
        s_z = np.sqrt(wc_z * hc_z)
        scale_z = size_z / s_z

        exemplar_img, scale_x = self.crop_and_pad(img, cx, cy, size_z, s_z, img_mean)

        w_x = w * scale_x
        h_x = h * scale_x

        return exemplar_img, scale_z, s_z, w_x, h_x

    def get_instance_image(self, img, bbox, size_z, size_x, context_amount, a_x, b_y, img_mean=None):

        cx, cy, w, h = bbox  # float type

        cx, cy = cx + a_x , cy + b_y
        wc_z = w + context_amount * (w + h)
        hc_z = h + context_amount * (w + h)
        s_z = np.sqrt(wc_z * hc_z) # the width of the crop box

        scale_z = size_z / s_z

        s_x = s_z * size_x / size_z
        instance_img, scale_x = self.crop_and_pad(img, cx, cy, size_x, s_x, img_mean)
        w_x = w * scale_x
        h_x = h * scale_x
        # point_1 = (size_x + 1) / 2 - w_x / 2, (size_x + 1) / 2 - h_x / 2
        # point_2 = (size_x + 1) / 2 + w_x / 2, (size_x + 1) / 2 + h_x / 2
        # frame = cv2.rectangle(instance_img, (int(point_1[0]),int(point_1[1])), (int(point_2[0]),int(point_2[1])), (0, 255, 0), 2)
        # cv2.imwrite('1.jpg', frame)
        return instance_img, w_x, h_x, scale_x

    def crop_and_pad(self, img, cx, cy, model_sz, original_sz, img_mean=None):
        im_h, im_w, _ = img.shape
        #print('original_sz', original_sz)

        xmin = cx - (original_sz - 1) / 2
        xmax = xmin + original_sz - 1
        ymin = cy - (original_sz - 1) / 2
        ymax = ymin + original_sz - 1

        left = int(self.round_up(max(0., -xmin)))
        top = int(self.round_up(max(0., -ymin)))
        right = int(self.round_up(max(0., xmax - im_w + 1)))
        bottom = int(self.round_up(max(0., ymax - im_h + 1)))

        xmin = int(self.round_up(xmin + left))
        xmax = int(self.round_up(xmax + left))
        ymin = int(self.round_up(ymin + top))
        ymax = int(self.round_up(ymax + top))
        r, c, k = img.shape
        if any([top, bottom, left, right]):
            te_im = np.zeros((r + top + bottom, c + left + right, k), np.uint8)  # 0 is better than 1 initialization
            te_im[top:top + r, left:left + c, :] = img
            if top:
                te_im[0:top, left:left + c, :] = img_mean
            if bottom:
                te_im[r + top:, left:left + c, :] = img_mean
            if left:
                te_im[:, 0:left, :] = img_mean
            if right:
                te_im[:, c + left:, :] = img_mean
            im_patch_original = te_im[int(ymin):int(ymax + 1), int(xmin):int(xmax + 1), :]
        else:
            im_patch_original = img[int(ymin):int(ymax + 1), int(xmin):int(xmax + 1), :]
        if not np.array_equal(model_sz, original_sz):
            #print('im_patch_original', im_patch_original.shape)
            im_patch = cv2.resize(im_patch_original, (model_sz, model_sz))  # zzp: use cv to get a better speed
        else:
            im_patch = im_patch_original
        scale = model_sz / im_patch_original.shape[0]
        return im_patch, scale

    def round_up(self, value):
        return round(value + 1e-6 + 1000) - 1000

    def _target(self):

        regression_target, conf_target = self.compute_target(self.anchors,
                                                             np.array(list(map(round,
                                                             self.ret['cx, cy, w, h']))))


        return regression_target, conf_target

    def compute_target(self, anchors, box):
        regression_target = self.box_transform(anchors, box)

        iou = self.compute_iou(anchors, box).flatten()
        #print(np.max(iou))
        pos_index = np.where(iou > config.pos_threshold)[0]
        neg_index = np.where(iou < config.neg_threshold)[0]
        label = np.ones_like(iou) * -1
        label[pos_index] = 1
        #print('label[pos_index]', len(label[pos_index]))
        label[neg_index] = 0
        #print('label[neg_index]', len(label[neg_index]))

        return regression_target, label

    def box_transform(self, anchors, gt_box):
        anchor_xctr = anchors[:, :1]
        anchor_yctr = anchors[:, 1:2]
        anchor_w = anchors[:, 2:3]
        anchor_h = anchors[:, 3:]
        gt_cx, gt_cy, gt_w, gt_h = gt_box

        target_x = (gt_cx - anchor_xctr) / anchor_w
        target_y = (gt_cy - anchor_yctr) / anchor_h
        target_w = np.log(gt_w / anchor_w)
        target_h = np.log(gt_h / anchor_h)
        regression_target = np.hstack((target_x, target_y, target_w, target_h))
        return regression_target

    def compute_iou_old(self, anchors, box):
        if np.array(anchors).ndim == 1:
            anchors = np.array(anchors)[None, :]
        else:
            anchors = np.array(anchors)
        if np.array(box).ndim == 1:
            box = np.array(box)[None, :]
        else:
            box = np.array(box)
        gt_box = np.tile(box.reshape(1, -1), (anchors.shape[0], 1))

        anchor_x1 = anchors[:, :1] - anchors[:, 2:3] / 2 + 0.5
        anchor_x2 = anchors[:, :1] + anchors[:, 2:3] / 2 - 0.5
        anchor_y1 = anchors[:, 1:2] - anchors[:, 3:] / 2 + 0.5
        anchor_y2 = anchors[:, 1:2] + anchors[:, 3:] / 2 - 0.5

        gt_x1 = gt_box[:, :1] - gt_box[:, 2:3] / 2 + 0.5
        gt_x2 = gt_box[:, :1] + gt_box[:, 2:3] / 2 - 0.5
        gt_y1 = gt_box[:, 1:2] - gt_box[:, 3:] / 2 + 0.5
        gt_y2 = gt_box[:, 1:2] + gt_box[:, 3:] / 2 - 0.5

        xx1 = np.max([anchor_x1, gt_x1], axis=0)
        xx2 = np.min([anchor_x2, gt_x2], axis=0)
        yy1 = np.max([anchor_y1, gt_y1], axis=0)
        yy2 = np.min([anchor_y2, gt_y2], axis=0)

        inter_area = np.max([xx2 - xx1, np.zeros(xx1.shape)], axis=0) * np.max([yy2 - yy1, np.zeros(xx1.shape)],
                                                                               axis=0)
        area_anchor = (anchor_x2 - anchor_x1) * (anchor_y2 - anchor_y1)
        area_gt = (gt_x2 - gt_x1) * (gt_y2 - gt_y1)
        iou = inter_area / (area_anchor + area_gt - inter_area + 1e-6)
        return iou

    def compute_iou(self, anchors, box):
        #print('anchors, box', anchors, box)
        gt_box = np.tile(box.reshape(1, -1), (anchors.shape[0], 1))

        anchor_x1 = anchors[:, :1] - anchors[:, 2:3] / 2 + 0.5
        anchor_x2 = anchors[:, :1] + anchors[:, 2:3] / 2 - 0.5
        anchor_y1 = anchors[:, 1:2] - anchors[:, 3:] / 2 + 0.5
        anchor_y2 = anchors[:, 1:2] + anchors[:, 3:] / 2 - 0.5

        gt_x1 = gt_box[:, :1] - gt_box[:, 2:3] / 2 + 0.5
        gt_x2 = gt_box[:, :1] + gt_box[:, 2:3] / 2 - 0.5
        gt_y1 = gt_box[:, 1:2] - gt_box[:, 3:] / 2 + 0.5
        gt_y2 = gt_box[:, 1:2] + gt_box[:, 3:] / 2 - 0.5

        xx1 = np.max([anchor_x1, gt_x1], axis=0)
        xx2 = np.min([anchor_x2, gt_x2], axis=0)
        yy1 = np.max([anchor_y1, gt_y1], axis=0)
        yy2 = np.min([anchor_y2, gt_y2], axis=0)

        inter_area = np.max([xx2 - xx1, np.zeros(xx1.shape)], axis=0) * np.max([yy2 - yy1, np.zeros(xx1.shape)],
                                                                               axis=0)
        area_anchor = (anchor_x2 - anchor_x1) * (anchor_y2 - anchor_y1)
        area_gt = (gt_x2 - gt_x1) * (gt_y2 - gt_y1)
        iou = inter_area / (area_anchor + area_gt - inter_area + 1e-6)
        return iou

    def _tranform(self):

        train_z_transforms = transforms.Compose([
            ToTensor()
        ])
        train_x_transforms = transforms.Compose([
            ToTensor()
        ])

        self.ret['train_x_transforms'] = train_x_transforms(self.ret['instance_img'])

        self.ret['train_z_transforms'] = train_z_transforms(self.ret['exemplar_img'])



    def __getitem__(self, index):
        if index >= len(self.sub_class_dir):
            index = random.choice(range(len(self.sub_class_dir)))
        if self.name == 'GOT-10k':
            if index == 8627 or index == 8629 or index == 9057 or index == 9058:
                index += 1

        self._pick_img_pairs(index)
        self.open()
        #self._pad_crop_resize()
        #self._generate_pos_neg_diff()
        self._tranform()
        regression_target, conf_target = self._target()
        self.count += 1

        return self.ret['train_z_transforms'], self.ret['train_x_transforms'], regression_target, conf_target.astype(np.int64)


    def __len__(self):
        return config.train_epoch_size*32

if __name__ == "__main__":

    root_dir = '/Users/arbi/Desktop'
    seq_dataset = GOT10k(root_dir, subset='val')
    train_data  = TrainDataLoader(seq_dataset)
    train_data.__getitem__(180)
