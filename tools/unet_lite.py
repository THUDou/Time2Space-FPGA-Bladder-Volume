import torch
import torch.nn as nn
import torch.nn.functional as F

def conv_bn(cin, cout, k=3, s=1, g=1):
    return nn.Sequential(
        nn.Conv2d(cin, cout, k, s, k // 2, groups=g, bias=False),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
    )

class DSBlock(nn.Module):

    def __init__(self, cin, cout, s=1):
        super().__init__()
        self.dw = nn.Sequential(
            nn.Conv2d(cin, cin, 3, s, 1, groups=cin, bias=False),
            nn.BatchNorm2d(cin),
            nn.ReLU(inplace=True),
        )
        self.pw = nn.Sequential(
            nn.Conv2d(cin, cout, 1, 1, 0, bias=False),
            nn.BatchNorm2d(cout),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.pw(self.dw(x))

class Up(nn.Module):
    def __init__(self, cin, cout, mode="nearest"):
        super().__init__()
        self.mode = mode
        if mode == "transpose":
            self.up = nn.ConvTranspose2d(cin, cin, 2, 2)
        else:
            self.up = nn.Upsample(scale_factor=2, mode="nearest")
        self.fuse = DSBlock(cin + cout, cout)

    def forward(self, x, skip):
        x = self.up(x)
        if x.shape[-2:] != skip.shape[-2:]:
            x = F.interpolate(x, size=skip.shape[-2:], mode="nearest")
        return self.fuse(torch.cat([x, skip], dim=1))

class UNetLite(nn.Module):
    def __init__(self, mode="nearest", width=1.0):
        super().__init__()
        w = lambda c: max(8, int(c * width))
        self.stem = conv_bn(1, w(16), 3, 2)
        self.e1 = DSBlock(w(16), w(32), 2)
        self.e2 = DSBlock(w(32), w(48), 2)
        self.e3 = DSBlock(w(48), w(64), 2)
        self.bott = DSBlock(w(64), w(96), 2)
        self.d3 = Up(w(96), w(64), mode)
        self.d2 = Up(w(64), w(48), mode)
        self.d1 = Up(w(48), w(32), mode)
        self.d0 = Up(w(32), w(16), mode)
        self.head = nn.Conv2d(w(16), 1, 1)

    def forward(self, x):
        s0 = self.stem(x)
        s1 = self.e1(s0)
        s2 = self.e2(s1)
        s3 = self.e3(s2)
        b = self.bott(s3)
        x = self.d3(b, s3)
        x = self.d2(x, s2)
        x = self.d1(x, s1)
        x = self.d0(x, s0)
        return self.head(x)

def count_params(m):
    return sum(p.numel() for p in m.parameters())

if __name__ == "__main__":
    m = UNetLite()
    x = torch.zeros(1, 1, 128, 128)
    y = m(x)
    print("params", count_params(m))
    print("out", tuple(y.shape))
