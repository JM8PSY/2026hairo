# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

# ホストPC（Mac / Linux）用の単体テストとシミュレータ
CXX ?= c++
CXXFLAGS ?= -std=c++17 -O1 -g -Wall -Wextra -Werror
INC = -I../include -I../lib/proto -I../lib/motor_core
LIB_SRC = ../lib/proto/proto.cpp ../lib/motor_core/motor_core.cpp
HDRS = $(wildcard ../include/*.h ../lib/*/*.h)
BUILD = build
UNAME := $(shell uname)
PTY_LIB = $(if $(filter Linux,$(UNAME)),-lutil,)

.PHONY: test sim clean

test: $(BUILD)/test_host $(BUILD)/motor_sim
	./$(BUILD)/test_host

sim: $(BUILD)/motor_sim

$(BUILD)/test_host: test_main.cpp $(LIB_SRC) $(HDRS) | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INC) -o $@ test_main.cpp $(LIB_SRC)

$(BUILD)/motor_sim: sim_main.cpp $(LIB_SRC) $(HDRS) | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INC) -o $@ sim_main.cpp $(LIB_SRC) $(PTY_LIB)

$(BUILD):
	mkdir -p $@

clean:
	rm -rf $(BUILD)
