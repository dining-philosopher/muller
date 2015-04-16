#!/usr/bin/python
# coding=utf-8

from pylab import *

from copy import *

import commands
import subprocess

import time

import os, sys

import bz2

import muller

# Muller's ratchet in finite population, genes have "good" and "bad" states (1 or 0),
# fitness is (1 + fb) ** E, where E is number of good genes

# N - number of organisms
# G - number of genes
# f - fitness of gene, F - fitness of organism (additive or multiplicative)
# M - mutation frequency
# B - probability of beneficial mutation (all other mutations are deleterious)
# fb - fitness benefit from beneficial mutation
# T - frequency of horizontal gene transfer (transformation)
# C - cost of horizontal gene transfer
# Tmut - mutation of T
# Ttransform - whether T and M gene will be transfered
# 
# Mmut - mutation of M
# 
# 

default_params = {"steps" : 200, "N" : 100, "G" : 100, "M" : 0.015, "B" : 0.1, "fb" : 0.05, "T" : 0., "Tmut" : 0., "Mmut" : 0., "Ttransform" : 1., "C" : 0., "X" : 1, "even": True, "constantX": True, "Binitial" : -1., "interval" : 1, "seed" : -1}
        #, "verbose" : False}

# extra_param_names = ["steps", "interval", "verbose"] # params that are not params of the model so should not be passed into model initialization

swigworld_param_names = ["N", "G", "B", "fb", "M", "Mmut", "T", "Tmut", "Ttransform", "C", "X", "even", "constantX", "Binitial", "seed"] # parameters for C++/swig World object initialization - unfortunately swig does not mention parameter names

exe_param_names = ["N", "G", "B", "fb", "M", "Mmut", "T", "Tmut", "Ttransform", "C", "Binitial", "interval", "seed"] # parameters needed for running c++ executable

def STATVARS(*names):
    o = []
    for name in names:
        o.extend([name + "avg", name + "std", name + "min", name + "max"])
    return o

stat_names = ["time"] + STATVARS("E", "EE", "X", "F", "M", "T", "EG") + ["Tplus"]

# stat_names = ["time", "Eavg", "Estd", "Emin", "Emax", "Favg", "Fstd", "Fmin", "Fmax", "Mavg", "Mstd", "Mmin", "Mmax", "Tavg", "Tstd", "Tmin", "Tmax", "Tplus", "EGavg", "EGstd", "EGmin", "EGmax"]


def chromosome_to_list(o, x):
    """Returns x-th chromosome of organism o as list. Direct iteration over chromosome leads to segmentation fault due to no range checking!"""
    return [int(o.chromosomes[x][g]) for g in xrange(o.G)]

class population_swig:
    
    def __init__(self, **kwargs):
        # filling attributes at once instead of mentioning each one
        # if parameter is not present in arguments then it will be taken from default_params
        self.params = copy(default_params)
        self.params.update(kwargs)
        for k, v in self.params.iteritems():
            setattr(self, k, v)
        
        
        if self.Binitial < 0:
            self.params["Binitial"] = self.B
            self.Binitial = self.B
        
        if self.seed < 0: # then random seed is generated by numpy random
            seed = randint(2**32)
            self.params["seed"] = seed
            self.seed = seed
        
        self.model_params = []
        for p in swigworld_param_names:
            self.model_params.append(self.params[p])
        self.model = muller.World(*self.model_params)
        
        # statistics initialization
        self.stat = {s: [] for s in stat_names}
        self.stat_names = stat_names

        
    def writestat(self):
        "returns string representing statistics table"
        # self.params["steps"] = len(self.stat["time"])
        s = "Model of Muller's ratchet https://github.com/dining-philosopher/muller.git\n"
        s += str(self.params) + "\n"
        s += "Statistics begin\n"
        s += " ".join(self.stat_names) + "\n"
        for i in xrange(len(self.stat["time"])):
            s += " ".join([str(self.stat[n][i]) for n in self.stat_names]) + "\n"
            # s +=  + "\n"
        return s
    
    def append_stat(self):
        self.model.calc_stat()
        for k, v in self.stat.iteritems():
            # self.stat[k].append(getattr(self.model, k))
            v.append(getattr(self.model, k))
        
    
    def run(self, steps = None, stat_func = None):
        """Runs simulation. If stat_func given, returns times and results of stat_func. stat_func must take population object and return list or tuple! So any custom statistics may be gathered. Also population manipulation is possible within stat_func."""
        custom_stat = []
        if type(self.stat[self.stat.keys()[0]]) == type(array([])):
            for k, v in self.stat.iteritems():
                self.stat[k] = list(v) # for restarts
        if steps:
            self.params["steps"] = steps + self.model.time
            self.steps = steps
        for i in xrange(self.steps - self.model.time):
            self.model.step()
            if self.model.time % self.interval == 0:
                self.append_stat()
            if stat_func != None: # gathering custom statistics
                custom_stat.append([self.model.time] + list(stat_func(self)))
        if stat_func != None:
            return custom_stat
        #for k, v in self.stat.iteritems():
        #    self.stat[k] = array(v) # for memory economy!
     


def readstat(text):
    # text is content of statistics file or output of modeling program
    # reads parameters as dictionary!
    # returns params, stats
    # TODO: generally move to csv, scipy.io or another module (also use bzip2)
    s = text.splitlines()
    params = {}
    for i in xrange(len(s)):
        if s[i][0] == "{":
            params = eval(s[i], {}, {})
        if s[i] == "Statistics begin":
            begin = i
            break
    
    # parsing header representing statistic variable names
    stat = {}
    stat_names = []
    for statname in s[begin+1].split():
        stat[statname] = []
        stat_names.append(statname)
        
    for line in s[begin+2:]:
        s = line.split()
        for i in xrange(len(s)):
            stat[stat_names[i]].append(float(s[i]))
    
    for k, v in stat.iteritems():
        stat[k] = array(v) # for memory economy!
    return params, stat


class Cache:
    
    def __init__(self, datadir = "trajectories", indexname = "dataindex.txt"):
        self.dataindex = []
        self.datadir = datadir
        self.indexname = indexname
        if os.path.isfile(indexname):
            self.readindex()
        else:
            f = open(indexname, "w")
            f.close()
    
    def readindex(self):
        self.dataindex = [] # array of dictionaries {"params" : {..}, "stat_names": {..}, "file": "smth"}
        f = open(self.indexname)
        s = f.read().splitlines()
        for i in xrange(len(s)):
            if s[i][0] == "{":
                self.dataindex.append(eval(s[i], {}, {}))
        f.close()
        
    def saveindex(self):
        f = open(self.indexname, "w")
        for d in self.dataindex:
            f.write(str(d) + "\n")
        f.close()
    
    def save(self, pop):
        "saves trajectory file and registers it in index file"
        if os.path.isfile(self.datadir):
            print "file", self.datadir, "exists! delete it or save in another place."
            return
        if not os.path.exists(self.datadir):
            os.mkdir(self.datadir)
        
        paramline = "_".join(map(lambda n: str(pop.params[n]), swigworld_param_names))
        filename = time.strftime("%Y-%m-%d_%H-%M-%S_") + paramline + ".txt.bz2"
        f = open(self.datadir + "/" + filename , "w")
        f.write(bz2.compress(pop.writestat()))
        f.close()
        
        self.readindex()
        self.dataindex.append({"params" : pop.params, "stat_names": pop.stat_names, "file": filename})
        self.saveindex()
        
    def select(self, default = True, filter_lambda = None, **kwargs):
        """Returns all cases satisfying lambda and having given parameters (and equal or more than given length).
        If default = True then omitted params will be at default values, otherwise it will filter only by mentioned parameters.
        If you get too few results - try default = False !
        
        Returns array of dictionaries {"params" : {..}, "stat_names": [..], "file": "smth"}.
        
        Examples:
        
        select(lambda a: a.G == 1. / a.M)
        select(G = 30, N = 100)"""
        
        # TODO: implement multiple selection, e. g select(G = 30, N = [10, 30, 100])
        
        params = {}
        if default == True:
            params = copy(default_params)
        params.update(kwargs)
        
        steps = params.pop("steps")
        # print "Seed:", params["seed"]
        if params["Binitial"] < 0:
            params["Binitial"] = params["B"]
        if params["seed"] < 0: # if seed < 0 then we can choose trajectory with any seed
            seed = params.pop("seed")
        
        found = self.dataindex
        for k, v in params.iteritems():
            # print k, v, len(found)
            found = filter(lambda a: a["params"][k] == v, found)
        found = filter(lambda a: a["params"]["steps"] >= steps, found)
        return found
        
        
    def select_one(self, **kwargs):
        """Returns one of saved trajectories with given parameters (all other parameters will be default), or None if there are no such files.
        
        Returns array of dictionaries {"params" : {..}, "stat_names": [..], "file": "smth"}."""
        
#        params = copy(default_params)
#        params.update(kwargs)
#        
#        steps = params.pop("steps")
#        # print "Seed:", params["seed"]
#        if params["Binitial"] < 0:
#            params["Binitial"] = params["B"]
#        if params["seed"] < 0: # if seed < 0 then we can choose trajectory with any seed
#            seed = params.pop("seed")
#        
#        found = self.dataindex
#        for k, v in params.iteritems():
#            # print k, v, len(found)
#            found = filter(lambda a: a["params"][k] == v, found)
#        found = filter(lambda a: a["params"]["steps"] >= steps, found)
        
        found = self.select(**kwargs)
        if len(found) == 0:
            return None
        
        # maxsteps = max(map(lambda a: a["params"]["steps"], found))
        # if maxsteps < steps:
        #     return None
        # found = filter(lambda a: a["params"]["steps"] == maxsteps, found)

        return found[randint(len(found))] # return some trajectory from those who have sufficient length
    
    def load_from_file(self, filename):
        f = open(self.datadir + "/" + filename)
        params, stat = readstat(bz2.decompress(f.read()))
        return params, stat
    
    def load_by_params(self, **kwargs):
        found = self.select_one(**kwargs)
        if found == None:
            return None
        filename = found["file"]
        return self.load_from_file(filename)

cache = Cache()

class population_cached(population_swig):
    
    def __init__(self, filename = None, new = False, **kwargs):
        """This object is needed to obtain trajectory of model with specified parameters. It tries to load it from disk or, if it is impossible, prepares model to run.
        
        Always call run() of created object! (But only once, multiple runs not tested.)
        
        Also it automatically saves trajectory after run (if needed).
        
        If filename is specified, then trajectory will be loaded from this file.
        If new = True, then new calculation will be initialized anyway.
        Otherwise trajectory with specified parameters will be loaded or, if it does not exist, calculation will be initialized."""
        if not new:
            if filename:
                data = cache.load_from_file(filename)
            else:
                data = cache.load_by_params(**kwargs)
        else:
            data = None
        if data:
            self._params, self._stat = data
            # for k, v in self._stat.iteritems():
            #     self._stat[k] = array(v) # already done in readstat()
            self.params, self.stat = self._params, self._stat
            for k, v in self.params.iteritems():
                setattr(self, k, v)
            print "Loaded data from file"
        else:
            population_swig.__init__(self, **kwargs)
            calc_units = self.N * self.G * self.X * self.steps
            print "Simulation will be done: ", calc_units, "calculation units or about ", 5e-8 * calc_units, " seconds"
        
    
    def run(self, steps = None):
        if hasattr(self, "model"): # if no cache available
            population_swig.run(self, steps)
            cache.save(self) # now this case is present in cache!
            print "Data saved in file"
            for k, v in self.stat.iteritems():
                self.stat[k] = array(v) # for memory economy!
            return
        if steps:
            if steps > self.params["steps"]:
                print "WARNING!! Requested length of simulation exceeds length of statistics in file!"
                self.params["steps"] = steps
                population_swig.__init__(self, **self.params)
                population_swig.run(self, steps)
                for k, v in self.stat.iteritems():
                    self.stat[k] = array(v[:(steps / self.interval)])
                cache.save(self) # now this case is present in cache!
                print "Data saved in file"
            else:
                self.params, self.stat = self._params, self._stat
                for k, v in self.stat.iteritems():
                #     self.stat[k] = array(v[:steps])
                    self.stat[k] = array(v[:(steps / self.interval)])
        else:
            self.params, self.stat = self._params, self._stat


def many_runs(run_n = 1, **kwargs):
    """Returns specified quantity of trajectories with the same parameters (except random seed). If there are not enough saved trajectories, returns all available and remaining as population objects to run.
    
    WARNING: if there are multiple trajectories with same seed, they all will be loaded (and so there will be duplicates in data set)!"""
    # TODO: solve warning
    found = cache.select(**kwargs)
    data = map(lambda a: population_cached(filename = a["file"]), found[:run_n])
    models = [population_cached(new = True, **kwargs) for i in xrange(run_n - len(found))]
    return data + models


# population = population_swig
population = population_cached
