// stemma offline note player for Faust synths (MIT licence).
//
// Usage: <binary> <sample_rate> <total_samples> <notes.txt> <out.f32>
// Each line of notes.txt: start_sample gate_samples release_samples freq_hz gain
// The DSP should expose the standard "freq", "gain" and "gate" controls. Every
// note gets its own DSP instance (unlimited polyphony, no voice stealing).
// Output is interleaved little-endian float32 with one frame per sample.

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

#include "faust/dsp/dsp.h"
#include "faust/gui/MapUI.h"
#include "faust/gui/meta.h"

<<includeIntrinsic>>

<<includeclass>>

int main(int argc, char* argv[]) {
    if (argc != 5) {
        std::fprintf(stderr, "usage: %s sr total notes.txt out.f32\n", argv[0]);
        return 2;
    }
    const int sr = std::atoi(argv[1]);
    const long total = std::atol(argv[2]);
    std::ifstream in(argv[3]);
    mydsp proto;
    const int outs = proto.getNumOutputs();
    if (outs < 1 || proto.getNumInputs() != 0) {
        std::fprintf(stderr, "Faust synth must have no inputs and at least one output\n");
        return 3;
    }
    std::vector<float> mix(static_cast<size_t>(total) * outs, 0.0f);
    const int block = 64;
    std::vector<std::vector<FAUSTFLOAT>> buf(outs, std::vector<FAUSTFLOAT>(block));
    std::vector<FAUSTFLOAT*> ptrs(outs);
    for (int c = 0; c < outs; ++c) ptrs[c] = buf[c].data();

    long start, gate, release;
    double freq, gain;
    while (in >> start >> gate >> release >> freq >> gain) {
        mydsp d;
        d.init(sr);
        MapUI ui;
        d.buildUserInterface(&ui);
        ui.setParamValue("freq", freq);
        ui.setParamValue("gain", gain);
        ui.setParamValue("gate", 1.0);
        const long len = gate + release;
        for (long pos = 0; pos < len && start + pos < total; pos += block) {
            if (pos >= gate) ui.setParamValue("gate", 0.0);
            const int n = static_cast<int>(std::min<long>(block, len - pos));
            d.compute(n, nullptr, ptrs.data());
            for (int i = 0; i < n && start + pos + i < total; ++i)
                for (int c = 0; c < outs; ++c)
                    mix[(start + pos + i) * outs + c] += buf[c][i];
        }
    }
    FILE* f = std::fopen(argv[4], "wb");
    if (!f) return 4;
    std::fwrite(mix.data(), sizeof(float), mix.size(), f);
    std::fclose(f);
    return 0;
}
