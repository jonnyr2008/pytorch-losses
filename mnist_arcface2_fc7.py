import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms
import numpy as np

print("Pytorch version:  " + str(torch.__version__))
use_cuda = torch.cuda.is_available()
print("Use CUDA: " + str(use_cuda))

# Cosface
from torch.autograd import Variable
from torch.utils.data import DataLoader
import torch.optim.lr_scheduler as lr_scheduler
from torch.autograd.function import Function
import math

from pdb import set_trace as bp

BATCH_SIZE = 100
FEATURES_DIM = 3
NUM_OF_CLASSES = 10

BATCH_SIZE_TEST = 1000
EPOCHS = 20
LOG_INTERVAL = 10

class Net(nn.Module):
    def __init__(self):
        super(Net, self).__init__()
        krnl_sz=3
        strd = 1
                    
        self.conv1 = nn.Conv2d(in_channels=1, out_channels=20, kernel_size=krnl_sz, stride=strd, padding=1)
        self.conv2 = nn.Conv2d(in_channels=20, out_channels=50, kernel_size=krnl_sz, stride=strd, padding=1)
        self.prelu1_1 = nn.PReLU()
        self.prelu1_2 = nn.PReLU()
        
        self.conv3 = nn.Conv2d(in_channels=50, out_channels=64, kernel_size=krnl_sz, stride=strd, padding=1)
        self.conv4 = nn.Conv2d(in_channels=64, out_channels=128, kernel_size=krnl_sz, stride=strd, padding=1)
        self.prelu2_1 = nn.PReLU()
        self.prelu2_2 = nn.PReLU()

        self.conv5 = nn.Conv2d(in_channels=128, out_channels=512, kernel_size=krnl_sz, stride=strd, padding=1)
        self.conv6 = nn.Conv2d(in_channels=512, out_channels=512, kernel_size=krnl_sz, stride=strd, padding=1)
        self.prelu3_1 = nn.PReLU()
        self.prelu3_2 = nn.PReLU()

        self.prelu_weight = nn.Parameter(torch.Tensor(1).fill_(0.25))

        self.fc1 = nn.Linear(3*3*512, 3)
        # self.fc2 = nn.Linear(3, 2)
        self.fc3 = nn.Linear(3, 10)

    def forward(self, x):
        mp_ks=2
        mp_strd=2

        x = self.prelu1_1(self.conv1(x))
        x = self.prelu1_2(self.conv2(x))
        x = F.max_pool2d(x, kernel_size=mp_ks, stride=mp_strd)

        x = self.prelu2_1(self.conv3(x))
        x = self.prelu2_2(self.conv4(x))
        x = F.max_pool2d(x, kernel_size=mp_ks, stride=mp_strd)

        x = self.prelu3_1(self.conv5(x))
        x = self.prelu3_2(self.conv6(x))
        x = F.max_pool2d(x, kernel_size=mp_ks, stride=mp_strd)

        x = x.view(-1, 3*3*512) # Flatten
        features3d = F.prelu(self.fc1(x), self.prelu_weight)
        x = self.fc3(features3d)
    
        return features3d, x
        
class LMCL_loss(nn.Module):

    def __init__(self, num_classes, feat_dim, device, s=7.0, m=0.2):
        super(LMCL_loss, self).__init__()
        self.feat_dim = feat_dim
        self.num_classes = num_classes
        self.s = s
        self.m = m
        self.weights = nn.Parameter(torch.randn(num_classes, feat_dim))
        self.device = device

        self.cos_m = math.cos(m)
        self.sin_m = math.sin(m)
        self.mm = math.sin(math.pi-m)*m
        self.threshold = math.cos(math.pi-m)

    def forward(self, feat, label, easy_margin=False):
        batch_size = feat.shape[0]
        norms = torch.norm(feat, p=2, dim=-1, keepdim=True)
        feat_l2norm = torch.div(feat, norms)
        feat_l2norm = feat_l2norm * self.s

        norms_w = torch.norm(self.weights, p=2, dim=-1, keepdim=True)
        weights_l2norm = torch.div(self.weights, norms_w)
        
        fc7 = torch.matmul(feat_l2norm, torch.transpose(weights_l2norm, 0, 1))

        # y_onehot = torch.FloatTensor(batch_size, self.num_classes).to(self.device)
        # y_onehot.zero_()
        # y_onehot = Variable(y_onehot)
        # y_onehot.scatter_(1, torch.unsqueeze(label, dim=-1), self.s_m)
        # output = fc7 - y_onehot


        # zy = mx.sym.pick(fc7, gt_label, axis=1)
        label = label.cpu()
        fc7 = fc7.cpu()

        target_one_hot = torch.zeros(len(label), NUM_OF_CLASSES).scatter_(1, label.unsqueeze(1), 1.)        
        zy = torch.addcmul(torch.zeros(fc7.size()), 1., fc7, target_one_hot)
        # bp()
        zy = zy.sum(-1)

        cos_t = zy/self.s
        # cos_m = math.cos(self.m)
        # sin_m = math.sin(m)
        # mm = math.sin(math.pi-m)*m
        # threshold = math.cos(math.pi-m)
        if easy_margin:
            cond = F.relu(cos_t)
        else:
            cond_v = cos_t - self.threshold
            cond = F.relu(cond_v)


        body = cos_t*cos_t
        body = 1.0-body
        sin_t = torch.sqrt(body)
        new_zy = cos_t*self.cos_m
        b = sin_t*self.sin_m
        new_zy = new_zy - b
        new_zy = new_zy*self.s
        if easy_margin:
            zy_keep = zy
        else:
            zy_keep = zy - self.s*self.mm

        # bp()
        new_zy = torch.where(cond.byte(), new_zy, zy_keep)

        diff = new_zy - zy
        # diff = mx.sym.expand_dims(diff, 1)
        diff = diff.unsqueeze(1)

        # gt_one_hot = mx.sym.one_hot(gt_label, depth = args.num_classes, on_value = 1.0, off_value = 0.0)
        # body = mx.sym.broadcast_mul(gt_one_hot, diff)
        body = torch.addcmul(torch.zeros(diff.size()), 1., diff, target_one_hot)

        output = fc7+body


        return output.to(self.device)


# def loss_function(output, target):
#       return F.nll_loss(F.log_softmax(output, dim=1), target)
  

def train(model, device, train_loader, loss_softmax, loss_lmcl, optimizer_nn, optimzer_lmcl, epoch):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(device), target.to(device)

        # optimizer.zero_grad()
        # output,_,_ = model(data)
        
        # loss = loss_function(output, target)
        
        # loss.backward()
        # optimizer.step()

        features, _ = model(data)
        logits = loss_lmcl(features, target)
        loss = loss_softmax(logits, target)

        _, predicted = torch.max(logits.data, 1)
        accuracy = (target.data == predicted).float().mean()

        optimizer_nn.zero_grad()
        optimzer_lmcl.zero_grad()

        loss.backward()

        optimizer_nn.step()
        optimzer_lmcl.step()

        if batch_idx % LOG_INTERVAL == 0:
            print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                epoch, batch_idx * len(data), len(train_loader.dataset),
                100. * batch_idx / len(train_loader), loss.item()))


def test(model, device, test_loader, loss_softmax, loss_lmcl):
    model.eval()
    # test_loss = 0
    correct = 0
    total = 0
    with torch.no_grad():
        for data, target in test_loader:
            data, target = data.to(device), target.to(device)

            feats, _ = model(data)
            logits = loss_lmcl(feats, target)
            _, predicted = torch.max(logits.data, 1)
            total += target.size(0)
            correct += (predicted == target.data).sum()

    # print('Test Accuracy of the model on the 10000 test images: %f %%' % (100 * correct / total))


    print('\nTest set:, Accuracy: {}/{} ({:.0f}%)\n'.format(
        correct, len(test_loader.dataset),
        100. * correct / len(test_loader.dataset)))    

    #         output,_,_ = model(data)
            
    #         test_loss += loss_function(output, target).item() # sum up batch loss

    #         pred = output.max(1, keepdim=True)[1] # get the index of the max log-probability
    #         correct += pred.eq(target.view_as(pred)).sum().item()

    # test_loss /= len(test_loader.dataset)

    # print('\nTest set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)\n'.format(
    #     test_loss, correct, len(test_loader.dataset),
    #     100. * correct / len(test_loader.dataset)))    

###################################################################

torch.manual_seed(1)
device = torch.device("cuda" if use_cuda else "cpu")

####### Data setup

kwargs = {'num_workers': 1, 'pin_memory': True} if use_cuda else {}
train_loader = torch.utils.data.DataLoader(
    datasets.MNIST('./data', train=True, download=True,
                   transform=transforms.Compose([
                       transforms.ToTensor(),
                       transforms.Normalize((0.1307,), (0.3081,))
                   ])),
    batch_size=BATCH_SIZE, shuffle=True, **kwargs)
test_loader = torch.utils.data.DataLoader(
    datasets.MNIST('./data', train=False, transform=transforms.Compose([
                       transforms.ToTensor(),
                       transforms.Normalize((0.1307,), (0.3081,))
                   ])),
    batch_size=BATCH_SIZE_TEST, shuffle=True, **kwargs)

####### Model setup

model = Net().to(device)
loss_softmax = nn.CrossEntropyLoss().to(device)
loss_lmcl = LMCL_loss(num_classes=10, feat_dim=FEATURES_DIM, device=device).to(device)

# optimzer nn
optimizer_nn = optim.SGD(model.parameters(), lr=0.001, momentum=0.9, weight_decay=0.0005)
sheduler_nn = lr_scheduler.StepLR(optimizer_nn, 20, gamma=0.5)

# optimzer cosface or lmcl
optimzer_lmcl = optim.SGD(loss_lmcl.parameters(), lr=0.01)
sheduler_lmcl = lr_scheduler.StepLR(optimzer_lmcl, 20, gamma=0.5)


for epoch in range(1, EPOCHS + 1):
    sheduler_nn.step()
    sheduler_lmcl.step()

    train(model, device, train_loader, loss_softmax, loss_lmcl, optimizer_nn, optimzer_lmcl, epoch)
    test(model, device, test_loader, loss_softmax, loss_lmcl)

torch.save(model.state_dict(),"mnist_cnn-cosface.pt")        
torch.save(loss_lmcl.state_dict(),"mnist_loss-cosface.pt")        
