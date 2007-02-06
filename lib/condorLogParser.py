#
# Description:
#   This module implements classes and functions to parse
#   the condor log files.
#
# Author:
#   Igor Sfiligoi (Feb 1st 2007)
#

# NOTE:
# Inactive files are log files that have only completed or removed entries
# Such files will not change in the future
#

import os,os.path,stat
import re,mmap
import cPickle,sets

# -------------- Single Log classes ------------------------

class cachedLogClass:
    # virtual, do not use
    # the Constructor needs to define logname and cachename (possibly by using clInit)
    # also loadFromLog, merge and isActive need to be implemented

    # init method to be used by real constructors
    def clInit(self,logname,cache_ext):
        self.logname=logname
        self.cachename=logname+cache_ext

    # compare to cache, and tell if the log file has changed since last checked
    def has_changed(self):
        if os.path.isfile(self.logname):
            fstat=os.lstat(self.logname)
            logtime=fstat[stat.ST_MTIME]
        else:
            return False # does not exist, so it could not change
        
        if os.path.isfile(self.cachename):
            fstat=os.lstat(self.cachename)
            cachetime=fstat[stat.ST_MTIME]
        else:
            return True # no cache, so it has changed for sure
        
        # both exist -> check if log file is newer
        return (logtime>cachetime)

    # load from the most recent one, and update the cache if needed
    def load(self):
        if not self.has_changed():
            # cache is newer, just load the cache
            return self.loadCache()

        while 1: #could need more than one loop if the log file is changing
            fstat=os.lstat(self.logname)
            start_logtime=fstat[stat.ST_MTIME]
            del fstat
            
            self.loadFromLog()
            try:
                self.saveCache()
            except IOError:
                return # silently ignore, this was a load in the end
            # the log may have changed -> check
            fstat=os.lstat(self.logname)
            logtime=fstat[stat.ST_MTIME]
            del fstat
            if logtime<=start_logtime:
                return # OK, not changed, can exit
        
        return # should never reach this point

        
    def loadCache(self):
        self.data=loadCache(self.cachename)
        return

    ####### PRIVATE ###########
    def saveCache(self):
        saveCache(self.cachename,self.data)
        return

        
# this class will keep track of:
#  jobs in various of statuses (Wait, Idle, Running, Held, Completed, Removed)
# These data is available in self.data dictionary
class logSummary(cachedLogClass):
    def __init__(self,logname):
        self.clInit(logname,".cstpk")

    def loadFromLog(self):
        jobs = parseSubmitLogFastRaw(self.logname)
        self.data = listAndInterpretRawStatuses(jobs)
        return

    def isActive(self):
        active=False
        for k in self.data.keys():
            if not (k in ['Completed','Removed']):
                if len(self.data[k])>0:
                    active=True # it is enought that at least one non Completed/removed job exist
        return active

    # merge self data with other info
    # return merged data, may modify other
    def merge(self,other):
        if other==None:
            return self.data
        else:
            for k in self.data.keys():
                try:
                    other[k]+=self.data[k]
                except: # missing key
                    other[k]=self.data[k]
                pass
            return other

    # diff self data with other info
    # return data[status]['Entered'|'Exited'] - list of jobs
    def diff(self,other):
        if other==None:
            outdata={}
            for k in self.data.keys():
                outdata[k]={'Exited':[],'Entered':self.data[k]}
            return outdata
        else:
            outdata={}
            
            keys={} # keys will contain the merge of the two lists
            
            for s in (self.data.keys()+other.keys()):
                keys[s]=None

            for s in keys.keys():
                if self.data.has_key(s):
                    sel=self.data[s]
                else:
                    sel=[]
                    
                if other.has_key(s):
                    oel=other[s]
                else:
                    oel=[]

                outdata_s={'Entered':[],'Exited':[]}
                outdata[s]=outdata_s

                sset=sets.Set(sel)
                oset=sets.Set(oel)

                outdata_s['Entered']=list(sset.difference(oset))
                outdata_s['Exited']=list(oset.difference(sset))
            return outdata
            

# this class will keep track of:
#  - counts of statuses (Wait, Idle, Running, Held, Completed, Removed)
#  - list of completed jobs
# These data is available in self.data dictionary
class logCompleted(cachedLogClass):
    def __init__(self,logname):
        self.clInit(logname,".clspk")

    def loadFromLog(self):
        tmpdata={}
        jobs = parseSubmitLogFastRaw(self.logname)
        status  = listAndInterpretRawStatuses(jobs)
        counts={}
        for s in status.keys():
            counts[s]=len(status[s])
        tmpdata['counts']=counts
        if status.has_key("Completed"):
            tmpdata['completed_jobs']=status['Completed']
        else:
            tmpdata['completed_jobs']=[]
        self.data=tmpdata
        return

    def isActive(self):
        active=False
        counts=self.data['counts']
        for k in counts.keys():
            if not (k in ['Completed','Removed']):
                if counts[k]>0:
                    active=True # it is enought that at least one non Completed/removed job exist
        return active


    # merge self data with other info
    # return merged data, may modify other
    def merge(self,other):
        if other==None:
            return self.data
        else:
            for k in self.data['counts'].keys():
                try:
                    other['counts'][k]+=self.data['counts'][k]
                except: # missing key
                    other['counts'][k]=self.data['counts'][k]
                pass
            other['completed_jobs']+=self.data['completed_jobs']
            return other


    # diff self data with other info
    def diff(self,other):
        if other==None:
            outcj={}
            outdata={'counts':self.data['counts'],'completed_jobs':outcj}
            for k in self.data['counts'].keys():
                outcj[k]={'Exited':[],'Entered':self.data[k]}
            return outdata
        else:
            outct={}
            outcj={'Entered':[],'Exited':[]}
            outdata={'counts':outct,'completed_jobs':outcj}

            keys={} # keys will contain the merge of the two lists
            for s in (self.data['counts'].keys()+other['counts'].keys()):
                keys[s]=None

            for s in keys.keys():
                if self.data['counts'].has_key(s):
                    sct=self.data['counts'][s]
                else:
                    sct=0
                    
                if other['counts'].has_key(s):
                    oct=other['counts'][s]
                else:
                    oct=0

                outct[s]=sct-oct

            sel=self.data['completed_jobs']
            oel=other['completed_jobs']
            sset=sets.Set(sel)
            oset=sets.Set(oel)

            outcj['Entered']=list(sset.difference(oset))
            outcj['Exited']=list(oset.difference(sset))

            return outdata

# this class will keep track of
#  counts of statuses (Wait, Idle, Running, Held, Completed, Removed)
# These data is available in self.data dictionary
class logCounts(cachedLogClass):
    def __init__(self,logname):
        self.logname=logname
        self.cachename=logname+".clcpk"

    def loadFromLog(self):
        tmpdata={}
        jobs = parseSubmitLogFastRaw(self.logname)
        self.data  = countAndInterpretRawStatuses(jobs)
        return

    def isActive(self):
        active=False
        for k in self.data.keys():
            if not (k in ['Completed','Removed']):
                if self.data[k]>0:
                    active=True # it is enought that at least one non Completed/removed job exist
        return active


    # merge self data with other info
    # return merged data, may modify other
    def merge(self,other):
        if other==None:
            return self.data
        else:
            for k in self.data.keys():
                try:
                    other[k]+=self.data[k]
                except: # missing key
                    other[k]=self.data[k]
                pass
            return other

    # diff self data with other info
    # return diff of counts
    def diff(self,other):
        if other==None:
            return self.data
        else:
            outdata={}
            
            keys={} # keys will contain the merge of the two lists
            for s in (self.data.keys()+other.keys()):
                keys[s]=None

            for s in keys.keys():
                if self.data.has_key(s):
                    sel=self.data[s]
                else:
                    sel=0
                    
                if other.has_key(s):
                    oel=other[s]
                else:
                    oel=0

                outdata[s]=sel-oel

            return outdata

# -------------- Multiple Log classes ------------------------

# this is a generic class
# while usefull, you probably don't wnat ot use it directly
class cacheDirClass:
    def __init__(self,logClass,
                 dirname,log_prefix,log_suffix=".log",cache_ext=".cifpk",
                 inactive_files=None): # if ==None, will be reloaded from cache
        self.cdInit(logClass,dirname,log_prefix,log_suffix,cache_ext,inactive_files)

    def cdInit(self,logClass,
               dirname,log_prefix,log_suffix=".log",cache_ext=".cifpk",
               inactive_files=None): # if ==None, will be reloaded from cache
        self.logClass=logClass # this is an actual class, not an object
        self.dirname=dirname
        self.log_prefix=log_prefix
        self.log_suffix=log_suffix
        self.inactive_files_cache=os.path.join(dirname,log_prefix+log_suffix+cache_ext)
        if inactive_files==None:
            if os.path.isfile(self.inactive_files_cache):
                self.inactive_files=loadCache(self.inactive_files_cache)
            else:
                self.inactive_files=[]
        else:
            self.inactive_files=inactive_files
        return
    

    # return a list of log files
    def getFileList(self, active_only):
        prefix_len=len(self.log_prefix)
        suffix_len=len(self.log_suffix)
        files=[]
        fnames=os.listdir(self.dirname)
        for fname in fnames:
            if  ((fname[:prefix_len]==self.log_prefix) and
                 (fname[-suffix_len:]==self.log_suffix) and
                 ((not active_only) or (not (fname in self.inactive_files))) 
                 ):
                files.append(fname)
                pass
            pass
        return files

    # compare to cache, and tell if the log file has changed since last checked
    def has_changed(self):
        ch=False
        fnames=self.getFileList(active_only=True)
        for fname in fnames:
            obj=self.logClass(os.path.join(self.dirname,fname))
            ch=(ch or obj.has_changed()) # it is enough that one changes
        return ch

    
    def load(self,active_only=True):
        mydata=None
        new_inactives=[]

        # get list of log files
        fnames=self.getFileList(active_only)

        # load and merge data
        for fname in fnames:
            obj=self.logClass(os.path.join(self.dirname,fname))
            obj.load()
            mydata=obj.merge(mydata)
            if not obj.isActive():
                new_inactives.append(fname)
                pass
            pass
        self.data=mydata

        # try to save inactive files in the cache
        # if one was looking at inactive only
        if active_only and (len(new_inactives)>0):
            self.inactive_files+=new_inactives
            try:
                saveCache(self.inactive_files_cache,self.inactive_files)
            except IOError:
                return # silently ignore, this was a load in the end

        return

    # diff self data with other info
    def diff(self,other):
        dummyobj=self.logClass("/dummy/dummy")
        dummyobj.data=self.data # a little rough but works
        return  dummyobj.diff(other) 
        
# this class will keep track of:
#  jobs in various of statuses (Wait, Idle, Running, Held, Completed, Removed)
# These data is available in self.data dictionary
class dirSummary(cacheDirClass):
    def __init__(self,dirname,log_prefix,log_suffix=".log",cache_ext=".cifpk",
                 inactive_files=None): # if ==None, will be reloaded from cache
        self.cdInit(logSummary,dirname,log_prefix,log_suffix,cache_ext,inactive_files)


# this class will keep track of:
#  - counts of statuses (Wait, Idle, Running, Held, Completed, Removed)
#  - list of completed jobs
# These data is available in self.data dictionary
class dirCompleted(cacheDirClass):
    def __init__(self,dirname,log_prefix,log_suffix=".log",cache_ext=".cifpk",
                 inactive_files=None): # if ==None, will be reloaded from cache
        self.cdInit(logCompleted,dirname,log_prefix,log_suffix,cache_ext,inactive_files)


# this class will keep track of
#  counts of statuses (Wait, Idle, Running, Held, Completed, Removed)
# These data is available in self.data dictionary
class dirCounts(cacheDirClass):
    def __init__(self,dirname,log_prefix,log_suffix=".log",cache_ext=".cifpk",
                 inactive_files=None): # if ==None, will be reloaded from cache
        self.cdInit(logCounts,dirname,log_prefix,log_suffix,cache_ext,inactive_files)



##############################################################################
#
# Low level functions
#
##############################################################################

################################
#  Condor log parsing functions
################################

# read a condor submit log
# return a dictionary of jobStrings each having the last statusString
# for example {'1583.004': '000', '3616.008': '009'}
def parseSubmitLogFastRaw(fname):
    jobs={}
    
    size = os.path.getsize(fname)
    fd=open(fname,"r")
    buf=mmap.mmap(fd.fileno(),size,access=mmap.ACCESS_READ)

    count=0
    idx=0

    while (idx+5)<size: # else we are at the end of the file
        # format
        # 023 (123.2332.000) Bla
        
        # first 3 chars are status
        status=buf[idx:idx+3]
        idx+=5
        # extract job id 
        i1=buf.find(")",idx)
        if i1<0:
            break
        jobid=buf[idx:i1-4]
        idx=i1+1

        jobs[jobid]=status
        i1=buf.find("...",idx)
        if i1<0:
            break
        idx=i1+4 #the 3 dots plus newline

    buf.close()
    fd.close()
    return jobs

# convert the log representation into (ClusterId,ProcessId)
# Return (-1,-1) in case of error
def rawJobId2Nr(str):
    arr=str.split(".")
    if len(arr)>=2:
        return (int(arr[0]),int(arr[1]))
    else:
        return (-1,-1) #invalid

# Status codes
# 000 - Job submitted
# 001 - Job executing
# 002 - Error in executable
# 003 - Job was checkpointed
# 004 - Job was evicted
# 005 - Job terminated
# 006 - Image size of job updated
# 007 - Shadow exception
# 008 - <Not used>
# 009 - Job was aborted
# 010 - Job was suspended
# 011 - Job was unsuspended
# 012 - Job was held
# 013 - Job was released
# 014 - Parallel node executed (not used here)
# 015 - Parallel node terminated (not used here)
# 016 - POST script terminated
# 017 - Job submitted to Globus
# 018 - Globus submission failed
# 019 - Globus Resource Back Up
# 020 - Detected Down Globus Resource
# 021 - Remote error
# 022 - Remote system call socket lost 
# 023 - Remote system call socket reestablished
# 024 - Remote system call reconnect failure
# 025 - Grid Resource Back Up
# 026 - Detected Down Grid Resource
# 027 - Job submitted to grid resource

# reduce the syayus to either Wait, Idle, Running, Held, Completed or Removed
def interpretStatus(status):
    if status==5:
        return "Completed"
    elif status==9:
        return "Removed"
    elif status in (1,3,6,10,11,22,23):
        return "Running"
    elif status==12:
        return "Held"
    elif status in (0,20,26):
        return "Wait"
    else:
        return "Idle"

# given a dictionary of job statuses (like the one got from parseSubmitLogFastRaw)
# will return a dictionary of sstatus counts
# for example: {'009': 25170, '012': 418, '005': 1503}
def countStatuses(jobs):
    counts={}
    for e in jobs.values():
        try:
            counts[e]+=1
        except: # there are only a few possible values, so using exceptions is faster
            counts[e]=1
    return counts

# given a dictionary of job statuses (like the one got from parseSubmitLogFastRaw)
# will return a dictionary of sstatus counts
# for example: {'Completed': 30170, 'Removed': 148, 'Running': 5013}
def countAndInterpretRawStatuses(jobs_raw):
    outc={}
    tmpc=countStatuses(jobs_raw)
    for s in tmpc.keys():
        i_s=interpretStatus(int(s))
        try:
            outc[i_s]+=tmpc[s]
        except:  # there are only a few possible values, so using exceptions is faster
            outc[i_s]=tmpc[s]
    return outc

# given a dictionary of job statuses (like the one got from parseSubmitLogFastRaw)
# will return a dictionary of jobs in each status
# for example: {'009': ["1.003","2.001"], '012': ["418.001"], '005': ["1503.001","1555.002"]}
def listStatuses(jobs):
    status={}
    for k,e in jobs.items():
        try:
            status[e].append(k)
        except: # there are only a few possible values, so using exceptions is faster
            status[e]=[k]
    return status

# given a dictionary of job statuses (like the one got from parseSubmitLogFastRaw)
# will return a dictionary of jobs in each status
# for example: {'Completed': ["2.003","5.001"], 'Removed': ["41.001"], 'Running': ["408.003"]}
def listAndInterpretRawStatuses(jobs_raw):
    outc={}
    tmpc=listStatuses(jobs_raw)
    for s in tmpc.keys():
        i_s=interpretStatus(int(s))
        try:
            outc[i_s]+=tmpc[s]
        except:  # there are only a few possible values, so using exceptions is faster
            outc[i_s]=tmpc[s]
    return outc

# read a condor submit log
# return a dictionary of jobIds each having the last status
# for example {(1583,4)': 0, (3616,8): 9}
def parseSubmitLogFast(fname):
    jobs_raw=parseSubmitLogFastRaw(fname)
    jobs={}
    for k in jobs_raw.keys():
        jobs[rawJobId2Nr(k)]=int(jobs_raw[k])
    return jobs

################################
#  Cache handling functions
################################

def loadCache(fname):
    fd=open(fname,"r")
    data=cPickle.load(fd)
    fd.close()
    return data

def saveCache(fname,data):
    # two steps; first create a tmp file, then rename
    tmpname=fname+(".tmp_%i"%os.getpid())
    fd=open(tmpname,"w")
    cPickle.dump(data,fd)
    fd.close()

    try:
        os.remove(fname)
    except:
        pass # may not exist
    os.rename(tmpname,fname)
        
    return
