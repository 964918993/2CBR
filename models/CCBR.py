""" cross-class bias

Author: Guanyu Zhu, 2022
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

from models.dgcnn import DGCNN
from models.attention import SelfAttention


class BaseLearner(nn.Module):
    """The class for inner loop."""
    def __init__(self, in_channels, params):
        super(BaseLearner, self).__init__()

        self.num_convs = len(params)
        self.convs = nn.ModuleList()

        for i in range(self.num_convs):
            if i == 0:
                in_dim = in_channels
            else:
                in_dim = params[i-1]
            self.convs.append(nn.Sequential(
                              nn.Conv1d(in_dim, params[i], 1),
                              nn.BatchNorm1d(params[i])))

    def forward(self, x):
        for i in range(self.num_convs):
            x = self.convs[i](x)
            if i != self.num_convs-1:
                x = F.relu(x)
        return x


class ProtoNet(nn.Module):
    def __init__(self, args):
        super(ProtoNet, self).__init__()
        self.n_way = args.n_way
        self.k_shot = args.k_shot
        self.dist_method = 'euclidean'
        self.in_channels = args.pc_in_dim
        self.n_points = args.pc_npts
        self.use_attention = args.use_attention

        self.encoder = DGCNN(args.edgeconv_widths, args.dgcnn_mlp_widths, args.pc_in_dim, k=args.dgcnn_k)
        self.base_learner = BaseLearner(args.dgcnn_mlp_widths[-1], args.base_widths)

        if self.use_attention:
            self.att_learner = SelfAttention(args.dgcnn_mlp_widths[-1], args.output_dim)
        else:
            self.linear_mapper = nn.Conv1d(args.dgcnn_mlp_widths[-1], args.output_dim, 1, bias=False)

        self.conv1 = nn.Conv1d(95, 192, kernel_size=1, bias=False)
        self.maxp1 = nn.MaxPool1d(4, stride=2)
        self.bn1 = nn.BatchNorm1d(192)


    def forward(self, support_x, support_y, query_x, query_y):
        """
        Args:
            support_x: support point clouds with shape (n_way, k_shot, in_channels, num_points)
            support_y: support masks (foreground) with shape (n_way, k_shot, num_points)
            query_x: query point clouds with shape (n_queries, in_channels, num_points)
            query_y: query labels with shape (n_queries, num_points), each point \in {0,..., n_way}
        Return:
            query_pred: query point clouds predicted similarity, shape: (n_queries, n_way+1, num_points)
        """

        support_x = support_x.view(self.n_way*self.k_shot, self.in_channels, self.n_points)
        support_feat = self.getFeatures(support_x)
        sf = support_feat

        support_feat = support_feat.view(self.n_way, self.k_shot, -1, self.n_points)
        query_feat = self.getFeatures(query_x)
        qf = query_feat

        s1 = self.maxp1(sf.permute(0, 2, 1).contiguous())
        s3 = F.relu(self.bn1(self.conv1(s1.permute(0, 2, 1).contiguous())))
        s5 = F.softmax(s3)

        q1 = self.maxp1(qf.permute(0, 2, 1).contiguous())
        q3 = F.relu(self.bn1(self.conv1(q1.permute(0, 2, 1).contiguous())))
        q5 = F.softmax(q3)

        att = s5 * q5

        sf.mul_(att)

        gap0 = torch.mean(qf[0], dim=0, keepdim=True) - torch.mean(sf[0], dim=0, keepdim=True)
        gap1 = torch.mean(qf[1], dim=0, keepdim=True) - torch.mean(sf[1], dim=0, keepdim=True)

        support_feat[0] = support_feat[0] + gap0.repeat(192, 1)
        support_feat[1] = support_feat[1] + gap1.repeat(192, 1)

        fg_mask = support_y
        bg_mask = torch.logical_not(support_y)

        support_fg_feat = self.getMaskedFeatures(support_feat, fg_mask)
        suppoer_bg_feat = self.getMaskedFeatures(support_feat, bg_mask)

        fg_prototypes, bg_prototype = self.getPrototype(support_fg_feat, suppoer_bg_feat)
        prototypes = [bg_prototype] + fg_prototypes

        similarity = [self.calculateSimilarity(query_feat, prototype, self.dist_method) for prototype in prototypes] 

        query_pred = torch.stack(similarity, dim=1)
        loss = self.computeCrossEntropyLoss(query_pred, query_y)
        return query_pred, loss


    def getFeatures(self, x):
        """
        Forward the input data to network and generate features
        :param x: input data with shape (B, C_in, L)
        :return: features with shape (B, C_out, L)
        """
        if self.use_attention:
            feat_level1, feat_level2 = self.encoder(x)
            feat_level3 = self.base_learner(feat_level2)
            att_feat = self.att_learner(feat_level2)
            return torch.cat((feat_level1, att_feat, feat_level3), dim=1)
        else:
            # return self.base_learner(self.encoder(x))
            feat_level1, feat_level2 = self.encoder(x)
            feat_level3 = self.base_learner(feat_level2)
            map_feat = self.linear_mapper(feat_level2)
            return torch.cat((feat_level1, map_feat, feat_level3), dim=1)

    def getMaskedFeatures(self, feat, mask):
        """
        Extract foreground and background features via masked average pooling

        Args:
            feat: input features, shape: (n_way, k_shot, feat_dim, num_points)
            mask: binary mask, shape: (n_way, k_shot, num_points)
        Return:
            masked_feat: masked features, shape: (n_way, k_shot, feat_dim)
        """
        mask = mask.unsqueeze(2)
        masked_feat = torch.sum(feat * mask, dim=3) / (mask.sum(dim=3) + 1e-5)
        return masked_feat

    def getPrototype(self, fg_feat, bg_feat):
        """
        Average the features to obtain the prototype

        Args:
            fg_feat: foreground features for each way/shot, shape: (n_way, k_shot, feat_dim)
            bg_feat: background features for each way/shot, shape: (n_way, k_shot, feat_dim)
        Returns:
            fg_prototypes: a list of n_way foreground prototypes, each prototype is a vector with shape (feat_dim,)
            bg_prototype: background prototype, a vector with shape (feat_dim,)
        """
        fg_prototypes = [fg_feat[way, ...].sum(dim=0) / self.k_shot for way in range(self.n_way)]
        bg_prototype =  bg_feat.sum(dim=(0,1)) / (self.n_way * self.k_shot)
        return fg_prototypes, bg_prototype

    def calculateSimilarity(self, feat,  prototype, method='cosine', scaler=20):
        """
        Calculate the Similarity between query point-level features and prototypes

        Args:
            feat: input query point-level features
                  shape: (n_queries, feat_dim, num_points)
            prototype: prototype of one semantic class
                       shape: (feat_dim,)
            method: 'cosine' or 'euclidean', different ways to calculate similarity
            scaler: used when 'cosine' distance is computed.
                    By multiplying the factor with cosine distance can achieve comparable performance
                    as using squared Euclidean distance (refer to PANet [ICCV2019])
        Return:
            similarity: similarity between query point to prototype
                        shape: (n_queries, 1, num_points)
        """
        if method == 'cosine':
            similarity = F.cosine_similarity(feat, prototype[None, ..., None], dim=1) * scaler
        elif method == 'euclidean':
            similarity = - F.pairwise_distance(feat, prototype[None, ..., None], p=2)**2
        else:
            raise NotImplementedError('Error! Distance computation method (%s) is unknown!' %method)
        return similarity

    def computeCrossEntropyLoss(self, query_logits, query_labels):
        """ Calculate the CrossEntropy Loss for query set
        """
        return F.cross_entropy(query_logits, query_labels)
