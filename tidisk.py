#!/usr/bin/python3

import os
import sys


class TIBase:
    def __init__(self, disk, au, type, mapType):
        self.disk = disk
        self.au = au
        self.type = type
        self.mapType = mapType
        self.hasErrors = False
        self.errors = []
        self.hasWarnings = False
        self.warnings = []
        self.fullPath = ""
        self.sectorAddress = TISectorAddress(disk, logicalSector=(au * disk.sectorsPerAU))

    def bytesToString(self, bytes):
        s = ''
        for b in bytes:
            if (b >= 32 and b < 127):
                s += chr(b)
            else:
                s += '\\x' + hex(b).lstrip('0x').zfill(2)
        return s

    def isValidName(self, bytes, asciiOnly=False):
        seenSpace = False
        for b in bytes:
            if (b == 0 or b == ord('.')):
                return False
            elif (asciiOnly and (b < 32 or b > 127)):
                return False
            elif (b == ord(' ')):
                seenSpace = True
            elif (seenSpace):
                return False
        return (bytes[0] != ord(' '))

    def wordToInt(self, bytes):
        return int(bytes[0]) * 256 + int(bytes[1])

    def littleEndianWordToInt(self, bytes):
        return int(bytes[1]) * 256 + int(bytes[0])

    def dateTimeToString(self, bytes):
        time = self.wordToInt(bytes[0:2])
        date = self.wordToInt(bytes[2:4])
        if (time == 0 and date == 0):
            return '                 '
        else:
            hour = time >> 11
            min = (time >> 5) & 0x3f
            sec = (time & 0x1f) * 2
            year = date >> 9
            mon = (date >> 5) & 0x0f
            day = date & 0x1f
            return str(year).zfill(2) + '-' + str(mon).zfill(2) + '-' + str(day).zfill(2) + ' ' + \
                   str(hour).zfill(2) + ':' + str(min).zfill(2) + ':' + str(sec).zfill(2)

    def export(self, dirPath):
        pass

    def printVal(self, label, val, just=30):
        print(label.ljust(just, ' ') + str(val))

    def addError(self, error):
        self.hasErrors = True
        self.errors.append(error)
        self.disk.addGlobalError(self, error)

    def printErrors(self, prefix=''):
        if (self.hasErrors):
            print(prefix + 'ERRORS:')
            for error in self.errors:
                print(prefix + '  ' + error)

    def addWarning(self, warning):
        self.hasWarnings = True
        self.warnings.append(warning)
        self.disk.addGlobalWarning(self, warning)

    def printWarnings(self, prefix=''):
        if (self.hasWarnings):
            print(prefix + 'WARNINGS:')
            for warning in self.warnings:
                print(prefix + '  ' + warning)


class TIVolumeBitmapAU(TIBase):
    def __init__(self, disk, au):
        super().__init__(disk, au, 'BITM', 'B')
        self.fullPath = disk.fullPath

class TIFreeAU(TIBase):
    def __init__(self, disk, au):
        super().__init__(disk, au, 'FREE', ' ')

class TIUnusedAU(TIBase):
    def __init__(self, disk, au):
        super().__init__(disk, au, 'UNUS', '.')

class TIUnknownAU(TIBase):
    def __init__(self, disk, au):
        super().__init__(disk, au, 'UNK', '?')


class TISectorAddress:
    def __init__(self, disk, cylinder=None, head=None, trackSector=None, logicalSector=None):
        self.disk = disk
        if (logicalSector is None):
            self.cylinder = cylinder
            self.head = head
            self.trackSector = trackSector
            self.logicalSector = trackSector + (head * disk.sectorsPerTrack) + \
                                 (cylinder * disk.numberOfHeads * disk.sectorsPerTrack)
        else:
            self.logicalSector = logicalSector
            self.trackSector = logicalSector % disk.sectorsPerTrack
            self.head = (logicalSector // disk.sectorsPerTrack) % disk.numberOfHeads
            self.cylinder = (logicalSector // disk.sectorsPerTrack) // (disk.numberOfHeads)

    def __str__(self):
        return str(self.logicalSector).rjust(5) + ' C:' + str(self.cylinder).zfill(3) + \
               ' H:' + str(self.head) + ' S:' + str(self.trackSector).zfill(2)


# Parse Directory Descriptor Record (DDR)
# 0-9   Directory name padded with spaces to the right
# 10-11 Total number of AUs (ignored)
# 12    Sectors per track (ignored)
# 13-15 "DIR"
# 16-17 Unused? (ignored)
# 18-21 Date and time of creation
# 22    Number of files
# 23    Numbr of subdirectories
# 24-25 Pointer to File Descriptor Index Record AU
# 26-27 Pointer to Parent DDR
# 28-255 Pointers to subdirectories (up to 114 AU pointers to DDRs, in alphabetical order)

class TIDir(TIBase):
    def __init__(self, disk, parent, au, ddr):
        magic = 'DIR'
        type = 'DDR'
        mapType = 'D'
        if (self == disk):
            magic = 'WIN'
            type = 'VIB'
            mapType = 'V'

        super().__init__(disk, au, type, mapType)

        self.parent = parent

        if (len(ddr) < disk.sectorSize):
            self.hasErrors = True
            raise Exception('DDR AU ' + str(au) + ' invalid length: ' + str(len(ddr)))
        if (self.bytesToString(ddr[13:16]) != magic):
            self.addWarning('invalid magic: ' + self.bytesToString(ddr[13:16]))
        if (not disk.testBitmap(au)):
            self.addWarning('marked as free in volume bitmap')

        name = ddr[0:10]
        self.name = self.bytesToString(name).rstrip()
        if (not self.isValidName(name)):
            self.addError('invalid name: ' + self.name)

        if (parent == disk):
            self.fullPath = self.name
        else:
            self.fullPath = parent.fullPath + '.' + self.name

        self.creationDateTime = self.dateTimeToString(ddr[18:22])

        self.numFiles = int(ddr[22])
        if (self.numFiles > 127):
            self.addError('too many files: ' + str(self.numFiles()))

        self.numSubdirs = int(ddr[23])
        if (self.numSubdirs > 114):
            self.addError('too many subdirectories: ' + str(self.numFiles()))

        self.FDIRAU = self.wordToInt(ddr[24:26])
        if (disk.isValidAU(self.FDIRAU)):
            self.FDIR = TIFDIR(self.disk, self, self.FDIRAU, disk.getAU(self.FDIRAU))
            if (self.numFiles != self.FDIR.numFiles):
                self.addError('file count mismatch with FDIR: ' + str(self.numFiles) + '/' + str(self.FDIR.numFiles))
        else:
            self.addError('invalid FDIR AU: ', + str(self.FDIR))
            self.FDIR = None

        self.parentDDR = self.wordToInt(ddr[26:28])
        if (not disk.isValidAU(self.parentDDR)):
            self.addWarning('invalid parent DDR AU: ' + str(self.parentDDR))
        elif (self.parentDDR != parent.au):
            self.addWarning('parent DDR mismatch: ' + str(self.parentDDR) + '/' + str(parent.au))

        self.subdirAUs = []
        self.subdirs = []
        sawZero = False
        for i in range(28, 256, 2):
            subdirAU = self.wordToInt(ddr[i:i+2])
            if (subdirAU == 0):
                sawZero = True
            elif (sawZero):
                self.addWarning('ignored non-zero subdir AU after zero at byte ' + str(i) + ': ' + str(subdirAU))
            else:
                self.subdirAUs.append(subdirAU)
                self.subdirs.append(TIDir(disk, self, subdirAU, disk.getAU(subdirAU)))

        if (self.numSubdirs != len(self.subdirs)):
            self.addError('subdir count mismatch: ' + str(self.numSubdirs) + '/' + str(len(self.subdirs)))

        disk.mapAU(au, self)

    def export(self, dirPath):
        dir = dirPath + '/' + self.name
        os.mkdir(dir)
        if (self.FDIR is not None):
            self.FDIR.export(dir)
        for subdir in self.subdirs:
            subdir.export(dir)

    def printVals(self, includeFiles=False, includeSubdirs=False, prefix=''):
        print(prefix + 'Directory at AU ' + str(self.au) + ':')
        self.printErrors(prefix + '  ')
        self.printWarnings(prefix + '  ')
        self.printVal(prefix + '  Name:', self.name)
        self.printVal(prefix + '  Full Path:', self.fullPath)
        self.printVal(prefix + '  Create Date/Time:', self.creationDateTime)
        self.printVal(prefix + '  Files:', self.numFiles)
        self.printVal(prefix + '  Subdirectories:', self.numSubdirs)
        self.printVal(prefix + '  FDIR AU:', self.FDIRAU)
        self.printVal(prefix + '  Parent DDR AU:', str(self.parentDDR) + ' (' + str(self.parent.au) + ')')
        self.printVal(prefix + '  Subdirectory AUs:', self.subdirAUs)

        self.FDIR.printVals(includeFiles, prefix + '  ')

        if (includeSubdirs):
            for dir in self.subdirs:
                dir.printVals(includeFiles, includeSubdirs, prefix + ' ')

    def printSubdirs(self, prefix=''):
        for dir in self.subdirs:
            print(prefix + dir.name.ljust(10) + '      DIR     ' +
                  str(dir.numFiles + dir.numSubdirs).rjust(8) + '  ' + dir.creationDateTime)

    def printTree(self, prefix=''):
        print(prefix + self.fullPath + ':')
        self.FDIR.printFiles(prefix + '  ')
        self.printSubdirs(prefix + '  ')
        for dir in self.subdirs:
            print()
            dir.printTree(prefix + '  ')


# Parse File Descriptor Index Record (FDIR)
# Up to 127 one word pointers to FDRs (0 = unused)
# Sorted alphabetically according to filenames in the FDRs
# Last entry (#128) always points back to associated DDR

class TIFDIR(TIBase):
    def __init__(self, disk, dir, au, fdir):
        super().__init__(disk, au, 'FDIR', 'I')

        self.dir = dir
        self.fullPath = dir.fullPath

        if (len(fdir) < disk.sectorSize):
            raise Exception('FDIR AU ' + str(au) + ' invalid length: ' + str(len(fdir)))
        if (not disk.testBitmap(au)):
            self.addWarning('marked as free in volume bitmap')

        self.parentDDR = self.wordToInt(fdir[254:256])
        if (self.parentDDR != dir.au):
            self.addError('parent DDR mismatch: DDR=' + str(self.parentDDR) + ' parentAU=' + str(parent.au))

        self.FDRAUs = []
        self.FDRs = []
        self.numFiles = 0
        sawZero = False
        for i in range(0, 254, 2):
            fdrAU = self.wordToInt(fdir[i:i+2])
            if (fdrAU):
                if (sawZero):
                    self.addWarning('ignored non-zero FDR AU after zero at byte ' + str(i) + ': ' + str(fdrAU))
                elif (disk.isValidAU(fdrAU)):
                    self.FDRAUs.append(fdrAU)
                    self.FDRs.append(TIFile(disk, dir, self, None, 0, 0, fdrAU, 0, disk.getSectorOfAU(fdrAU, 0)))
                    self.numFiles += 1
                else:
                    self.addError('invalid FDR AU at byte ' + str(i) + ': ' + str(fdrAU))
            else:
                sawZero = True

        if (self.numFiles != dir.numFiles):
            self.addError('DDR/FDIR file count mismatch: DDR=' + str(dir.numFiles) + ' FDIR=' + str(self.numFiles))

        disk.mapAU(au, self)

    def export(self, dirPath):
        for fdr in self.FDRs:
            fdr.export(dirPath)

    def printVals(self, includeFiles=False, prefix=''):
        print(prefix + 'FDIR at AU ' + str(self.au) + ':')
        self.printErrors(prefix + '  ')
        self.printWarnings(prefix + '  ')
        self.printVal(prefix + '  Files:', self.numFiles)
        self.printVal(prefix + '  FDR AUs:', self.FDRAUs)

        if (includeFiles):
            for fdr in self.FDRs:
                fdr.printVals(prefix + ' ')

    def printFiles(self, prefix=''):
        for fdr in self.FDRs:
            flags = ' '
            if (fdr.isProtected):
                flags = 'P'
            if (fdr.isModifiedSinceBackup):
                flags += 'B  '
            else:
                flags += '   '

            print(prefix + fdr.name.ljust(10) + '  ' + flags + fdr.getFileType() + '  ' +
                  fdr.creationDateTime + '  ' + fdr.modificationDateTime)


# Parse File Descriptor Record (FDR)
# 0-9   File name padded with spaces to the right
# 10-11 Extended record length (if data file has a record length greater than 255 bytes)
# 12    File status flags
#       Bit 7:  Record type (0=FIXED, 1=VARIABLE) [MSb]
#       Bit 6:  Reserved for future expansion
#       Bit 5:  DSK1 file emulation flag (0=no, 1=yes)
#       Bit 4:  Backup flag (0=not modified since last backup, 1=modified since last backup)
#       Bit 3:  Protect flag (0=unprotected, 1=protected)
#       Bit 2:  Reserved for future data type expansion
#       Bit 1:  Binary/ASCII data (0=ASCII [DISPLAY], 1=Binary [INTERNAL])
#       Bit 0:  Program/data file indicator (0=data file, 1=program file) [LSb]
# 13    Number of records per sector
# 14-15 Number of sectors currently allocated (most significant nibble is in extended information)
# 16    End of file offset - Contains the offset into the highest sector used in the case of program and variable
#       length files. When this field is not 0, the byte length of a program file calculates as (n-1)*256 + eof,
#       where n is the number of sectors allocated to this file, and eof is the value of this field.
#       When 0, the length is n*256
# 17    Logical record length - If this entry is zero and it is a data file, then the record length is given in the
#       extended record length
# 18-19 Number of level 3 records allocated (little-endian) - In the case of FIXED length record files,
#       this contains the highest record actually written to.  In the case of VARIABLE length record files
#       it contains the count of sectors written to.  The most significant nibble of this field is located
#       in the Extended Information word.  Note: the bytes in this field are in reverse order.
# 20-23 Date and time of creation
# 24-27 Date and time of last update
# 28-29 "FI" or 0x00 0x00
# 30-31 Pointer to previous FDR AU in chain - In case that a single FDR cannot hold all cluster entries
#       (for heavily fractured files), a chain of FDRs is created. If this FDR is the first one in the chain,
#       the value is zero. Otherwise, the value points to the AU of its predecessor.
# 32-33 Pointer to next FDR AU in chain - points to the AU of the successor FDR, or contains zero if this FDR
#       is the last in the chain or if it is the only FDR of this file.
# 34-35 Number of AUs allocated for this FDR - gives the number of AUs that have been allocated to this FDR.
#       This is useful in determining quickly if this is the desired FDR, or a predecessor or successor is.
# 36-37 Pointer to FDIR - points to the FDIR which points to this file.
# 38-39 Extended information
#       This word is divided into 4 nibbles. The leftmost nibble is the most significant nibble (MSN) of the
#       number of sectors allocated to the file. The next nibble is the MSN of the number of sectors actually
#       used in a variable record file. The next nibble is the sector number within an AU pointing to the
#       predecessor FDR. The last nibble is the sector within an AU pointing to the successor FDR.
#       Nibble 0 [MSN]: Number of allocated sectors / 65536
#       Nibble 1:       Number of sectors of a VARIABLE file / 65536
#       Nibble 2:       Sector number in AU pointing to previous FDR
#       Nibble 3 [LSN]: Sector number of AU pointing to next FDR
# 40-255 Data chain pointer blocks
# This section of the FDR contain data block pointer clusters. Each cluster is a two-word entity.
# The first word points to the first AU in the data block and the second word points to the last AU in the data block.
# The number of contiguous AUs allocated by the cluster is the difference plus 1.

class TIFile(TIBase):
    def __init__(self, disk, dir, fdir, prevFDR, prevFDRAU, prevFDRAUSectorOffset, au, sectorOffset, fdr):
        super().__init__(disk, au, 'FDR', 'F')

        self.dir = dir
        self.fdir = fdir
        self.prevFDR = prevFDR
        self.nextFDR = None
        self.sectorOffset = sectorOffset
        self.b = fdr

        if (sectorOffset > 0):
            disk.mapSectorOfAU(au, sectorOffset, self)
        else:
            disk.mapAU(au, self)

        if (len(fdr) < disk.sectorSize):
            raise Exception('FDR AU ' + str(au) + ' invalid length: ' + str(len(fdr)))

        if ((self.bytesToString(fdr[28:30]) != 'FI') and (self.wordToInt(fdr[28:30]) != 0)):
            self.addWarning('invalid magic: ' + self.bytesToString(fdr[28:30]))

        if (not disk.testBitmap(au)):
            self.addWarning('marked as free in volume bitmap')

        if (sectorOffset and prevFDRAU == 0):
            self.addError('has prevFDRAU=' + str(prevFDRAU) + ' with non-zero sectorOffset=' + str(sectorOffset))

        name = fdr[0:10]
        self.name = self.bytesToString(name).rstrip()
        if (not self.isValidName(name)):
            self.addError('invalid name: ' + self.name)

        if (dir == disk):
            self.fullPath = self.name
        else:
            self.fullPath = dir.fullPath + '.' + self.name

        self.extendedRecordLength = self.wordToInt(fdr[10:12])
        self.flags = fdr[12]
        self.isVariable = bool(self.flags & 0x80)
        self.isDSK1Emu = bool(self.flags & 0x20)
        self.isModifiedSinceBackup = bool(self.flags & 0x10)
        self.isProtected = bool(self.flags & 0x08)
        self.isInternal = bool(self.flags & 0x02)
        self.isProgram = bool(self.flags & 0x01)

        self.recordsPerSector = int(fdr[13])
        self.numSectorsAllocated = self.wordToInt(fdr[14:16])

        self.EOFOffset = int(fdr[16])
        self.logicalRecordLength = int(fdr[17])

        self.recordLength = self.logicalRecordLength
        if ((not self.isProgram or self.isDSK1Emu) and (self.logicalRecordLength == 0)):
            self.recordLength = self.extendedRecordLength

        self.numLevel3Records = self.littleEndianWordToInt(fdr[18:20])

        self.creationDateTime = self.dateTimeToString(fdr[20:24])
        self.modificationDateTime = self.dateTimeToString(fdr[24:28])

        self.prevFDRAU = self.wordToInt(fdr[30:32])
        if (self.prevFDRAU != prevFDRAU):
            self.addError('previous FDR AU mismatch: ' + str(self.prevFDRAU) + '/' + str(prevFDRAU))

        self.nextFDRAU = self.wordToInt(fdr[32:34])
        if (not disk.isValidAU(self.nextFDRAU)):
            self.addError('invalid next FDR AU: ' + str(self.nextFDRAU))

        self.numAllocatedAUs = self.wordToInt(fdr[34:36])

        self.FDIRAU = self.wordToInt(fdr[36:38])
        if (self.FDIRAU != fdir.au):
            self.addError('FDIR AU mismatch: ' + str(self.FDIRAU) + '/' + str(fdir.au))

        self.extendedInfo = self.wordToInt(fdr[38:40])
        self.numSectorsAllocated += int((self.extendedInfo >> 12) & 0x0f) * 65536
        if (self.isVariable):
            self.numLevel3Records += int((self.extendedInfo >> 8) & 0x0f) * 65536
        self.prevFDRAUSectorOffset = int((self.extendedInfo >> 4) & 0x0f)
        self.nextFDRAUSectorOffset = int(self.extendedInfo & 0x0f)

        if (self.prevFDRAUSectorOffset != prevFDRAUSectorOffset):
            self.addError('previous FDR AU sector offset mismatch: ' +
                          str(self.prevFDRAUSectorOffset) + '/' + str(prevFDRAUSectorOffset))

        if (not disk.isValidSectorOfAU(self.prevFDRAU, self.prevFDRAUSectorOffset)):
            self.addError('previous FDR AU sector offset invalid: AU=' + str(prevFDRAU) +
                          ' sector=' + str(prevFDRAUSectorOffset))

        self.programLength = 0
        if (self.isProgram):
            if (self.EOFOffset > 0):
                self.programLength = (self.numSectorsAllocated - 1) * disk.sectorSize + self.EOFOffset
            else:
                self.programLength = self.numSectorsAllocated * disk.sectorSize


        self.dataChainPointers = []
        allocatedAUs = 0
        sawZero = False
        for i in range(40, 256, 4):
            start = self.wordToInt(fdr[i:i+2])
            end = self.wordToInt(fdr[i+2:i+4])
            if ((end < start) or ((start == 0) and (end != 0))):
                self.addError('data chain at byte ' + str(i) + ': invalid: start=' + str(start) + ', end=' + str(end))
            elif (start == 0):
                sawZero = True
            elif (sawZero):
                self.addWarning('ignored non-zero data chain AU after zero at byte ' + str(i) + ': [' +
                                str(start) + ',' + str(end) + ']')
            elif (not self.hasErrors):
                # don't bother mapping the data chain if there are errors with this FDR as the chain is likely garbage
                dataChain = TIAURange(disk, self, start, end)
                if (dataChain.isValid()):
                    self.dataChainPointers.append(dataChain)
                    for dataAU in range(start, end+1):
                        disk.mapAU(dataAU, dataChain)
                        if (not disk.testBitmap(dataAU)):
                            self.addWarning('data chain AU ' + str(dataAU) + ' marked as free in volume bitmap')

                    allocatedAUs += dataChain.getNumAUs()
                else:
                    self.addError('invalid data chain at byte ' + str(i) + ': [' + str(start) + ',' + str(end) + ']')

        if (allocatedAUs != self.numAllocatedAUs):
            self.addError('allocated AU mismatch: ' + str(allocatedAUs) + '/' + str(self.numAllocatedAUs))

        # More logical validations
        if (self.isProgram):
            # Program files should have zeros for logical record length and records per sector
            if (self.logicalRecordLength != 0):
                self.addWarning('logical record length is ' + str(self.logicalRecordLength) +
                                ', expected 0 for PROGRAM type')
            if (self.recordsPerSector != 0):
                self.addWarning('records per sector is ' + str(self.recordsPerSector) +
                                ', expected 0 for PROGRAM type')
            if (self.numLevel3Records != 0):
                self.addWarning('number of level 3 records is ' + str(self.numLevel3Records) +
                                ', expected 0 for PROGRAM type')
        else:
            if (self.logicalRecordLength == 0):
                self.addError('logical record length is 0, expected non-zero for non-PROGRAM type')
            if (self.isVariable):
                # level 3 records = number of sectors within file with data written to for VARIABLE data
                if (self.numLevel3Records > self.numSectorsAllocated):
                    self.addError('number of sectors with data (L3 records) ' + str(self.numLevel3Records) +
                                  ' > total allocated sectors ' + str(self.numSectorsAllocated))
            else:
                # level 3 records = number of records written for FIXED files
                if (self.recordsPerSector == 0):
                    self.addError('records per sector is 0, expected non-zero for FIXED type')
                elif (self.numLevel3Records > (self.recordsPerSector * self.numSectorsAllocated)):
                    self.addError('L3 records is ' + str(self.numLevel3Records) + ' but max allocated records is ' +
                                  str(self.recordsPerSector * self.numSectorsAllocated))

        if (self.nextFDRAU != 0):
            if (disk.isValidSectorOfAU(self.nextFDRAU, self.nextFDRAUSectorOffset)):
                self.nextFDR = TIFile(disk, dir, fdir, self, au, sectorOffset,
                                      self.nextFDRAU, self.nextFDRAUSectorOffset,
                                      disk.getSectorOfAU(self.nextFDRAU, self.nextFDRAUSectorOffset))
            else:
                self.addError('next FDR AU sector offset invalid: AU=' + str(self.nextFDRAU) +
                              ' sector=' + str(self.nextFDRAUSectorOffset))

        if (self.getFileSectorsInUse() > self.numSectorsAllocated):
            self.addWarning('sectors in use ' + str(self.getFileSectorsInUse()) + ' > sectors allocated ' +
                            str(self.numSectorsAllocated))

    def getFirstFDR(self):
        fdr = self
        while fdr.prevFDR is not None:
            fdr = fdr.prevFDR
        return fdr

    def getFileAllocatedSize(self):
        return getFirstFDR().numSectorsAllocated * self.disk.sectorSize

    def getFileSectorsInUse(self):
        fdr = self.getFirstFDR()
        if (fdr.isProgram):
            numSectors = self.programLength // self.disk.sectorSize
            if (fdr.programLength % self.disk.sectorSize > 0):
                numSectors += 1
            return numSectors
        elif (fdr.isVariable):
            # numLevel3Records contains the number of sectors written to for VARIABLE files
            return fdr.numLevel3Records
        elif (fdr.recordLength <= self.disk.sectorSize):
            # Extended record length for FIXED files is <= the size of a sector
            # Can't rely on self.recordsPerSector to be set correctly, so calculate it
            recordLength = fdr.recordLength
            if (recordLength == 0):
                recordLength = 256
            recordsPerSector = self.disk.sectorSize // recordLength
            numSectors = fdr.numLevel3Records // recordsPerSector
            if (fdr.numLevel3Records % recordsPerSector > 0):
                numSectors += 1
            return numSectors
        else:
            # Extended record length for FIXED files is greater than the size of a sector
            sectorsPerRecord = fdr.recordLength // self.disk.sectorSize
            if (fdr.recordLength % self.disk.sectorSize > 0):
                sectorsPerRecord += 1
            return (fdr.numLevel3Records * sectorsPerRecord)

    def containsDataInAU(self, au):
        fdr = self.getFirstFDR()
        lastRelativeSector = fdr.getFileSectorsInUse() - 1
        relativeSector = 0
        while ((fdr is not None) and (relativeSector <= lastRelativeSector)):
            for dcp in fdr.dataChainPointers:
                if (dcp.containsAU(au)):
                    return True
                relativeSector += dcp.getNumSectors()
            fdr = fdr.nextFDR
        return False

    def getFileType(self):
        if (self.isDSK1Emu):
            return 'DSK1EMU ' + str(self.programLength).rjust(8)
        elif (self.isProgram):
            return 'PROGRAM ' + str(self.programLength).rjust(8)
        elif (self.isInternal):
            if (self.isVariable):
                return 'INT/VAR ' + str(self.recordLength).rjust(8)
            else:
                return 'INT/FIX ' + str(self.recordLength).rjust(8)
        elif (self.isVariable):
            return 'DIS/VAR ' + str(self.recordLength).rjust(8)
        else:
            return 'DIS/FIX ' + str(self.recordLength).rjust(8)

    def export(self, dirPath):
        fdr = self.getFirstFDR()
        f = open(dirPath + '/' + fdr.name.replace('/', '.'), 'wb')
        header = bytearray(128)
        header[0] = 0x07                # TIFILES header
        header[1] = ord('T')
        header[2] = ord('I')
        header[3] = ord('F')
        header[4] = ord('I')
        header[5] = ord('L')
        header[6] = ord('E')
        header[7] = ord('S')
        header[8:10] = fdr.b[14:16]     # Nunber of allocated sectors
        header[10] = fdr.b[12]          # Flags
        header[11] = fdr.b[13]          # Records per sector
        header[12] = fdr.b[16]          # EOF offset
        header[13] = fdr.b[17]          # Logical record length
        header[14:16] = fdr.b[18:20]    # Number of level 3 records
        header[16:26] = fdr.b[0:10]     # Filename
        header[26] = 0x00               # MXT (not used)
        header[27] = 0x00               # Reserved (not used)
#        header[28] = 0xff               # Extended header flag
#        header[29] = 0xff               # Extended header flag
#        header[30:38] = fdr.b[20:28]    # Creation and update date and time
        f.write(header)

        sectorNum = 0
        while (fdr is not None):
            for dcp in fdr.dataChainPointers:
                for au in range(dcp.start, dcp.end +1 ):
                    for sector in range(0, self.disk.sectorsPerAU):
                        if (sectorNum < fdr.numSectorsAllocated):
                            f.write(self.disk.getSectorOfAU(au, sector))
                            sectorNum += 1
            fdr = fdr.nextFDR

        f.close()


    def printVals(self, prefix=''):
        print(prefix + 'File at AU ' + str(self.au) + ':')
        self.printErrors(prefix + '  ')
        self.printWarnings(prefix + '  ')
        self.printVal(prefix + '  Name:', self.name)
        self.printVal(prefix + '  Full Path:', self.fullPath)
        self.printVal(prefix + '  Type:', self.getFileType())
        self.printVal(prefix + '  Needs Backup:', self.isModifiedSinceBackup)
        self.printVal(prefix + '  Protected:', self.isProtected)
        self.printVal(prefix + '  Records/Sector:', self.recordsPerSector)
        self.printVal(prefix + '  Sectors Alloc:', self.numSectorsAllocated)
        self.printVal(prefix + '  EOF Offset', self.EOFOffset)
        self.printVal(prefix + '  L3 Records Alloc:', self.numLevel3Records)
        self.printVal(prefix + '  Create Date/Time:', self.creationDateTime)
        self.printVal(prefix + '  Modify Date/Time:', self.modificationDateTime)
        self.printVal(prefix + '  Prev FDR AU:', str(self.prevFDRAU) + ' (' + str(self.prevFDRAUSectorOffset) + ')')
        self.printVal(prefix + '  Next FDR AU:', str(self.nextFDRAU) + ' (' + str(self.nextFDRAUSectorOffset) + ')')
        self.printVal(prefix + '  Allocated AUs:', self.numAllocatedAUs)
        self.printVal(prefix + '  FDIR AU:', self.FDIRAU)
        self.printVal(prefix + '  Extended Info:', hex(self.extendedInfo))
        dataChain = ''
        for dcp in self.dataChainPointers:
            dataChain += str(dcp.start) + '-' + str(dcp.end) + ' '
        self.printVal(prefix + '  Data Chain:', dataChain)
        if (self.nextFDR is not None):
            self.nextFDR.printVals(prefix + '  ')


class TIAURange(TIBase):
    def __init__(self, disk, fdr, start, end):
        super().__init__(disk, fdr.au, 'DCPB', 'o')
        self.start = start
        self.end = end
        self.fullPath = fdr.fullPath

    def isValid(self):
        return ((self.start > 0) and (self.end >= self.start) and
                self.disk.isValidAU(self.start) and self.disk.isValidAU(self.end))

    def getNumAUs(self):
        if (self.isValid()):
            return self.end - self.start + 1
        else:
            return 0

    def getNumSectors(self):
        return self.getNumAUs() * self.disk.sectorsPerAU

    def containsAU(self, au):
        return (self.isValid() and au >= self.start and au <= self.end)

    def containsSector(self, sector):
        return (self.isValid() and sector >= self.start * self.disk.sectorsPerAU and
                sector <= self.end * self.disk.sectorsPerAU)


# Parse Volume Information Block (Sector 0)
# 0-9   Volume name padded with spaces to the right
# 10-11 Total number of AUs
# 12    Sectors per track
# 13-15 "WIN" (Alternate: AUs allocated for file/dir headers, Step Speed, First cyl with reduced wtite current)
# 16-17 Hard disk parameters
#       Bits 0-3:   Sectors per AU - 1
#       Bits 4-7:   Number of heads - 1
#       Bit  8:     Buffered head stepping? (1=yes)
#       Bits 9-15:  Write pre-compensation track, divided by 16
# 18-21 Date and time of creation
# 22    Number of files
# 23    Numbr of subdirectories
# 24-25 Pointer to File Descriptor Index Record AU
# 26-27 Pointer to DSK1 emulation file FDR AU
# 28-255 Pointers to subdirectories (up to 114 AU pointers to DDRs, in alphabetical order)
#
# Sectors 1-31 contain the bit map
# Byte 0 MSB = AU 0 (VIB)
# Byte 0 LSB = AU 7
# Byte 1 MSB = AU 8
# ...etc...

class TIDisk(TIDir):
    def __init__(self, rawBytes):
        self.b = rawBytes
        self.bsize = len(self.b)
        self.sectorSize = 256
        self.globalErrors = {}
        self.globalWarnings = {}

        if (self.bsize < self.sectorSize * 32):
            raise Exception('Invalid VIB: len=' + str(self.bsize))

        self.totalAUs = self.wordToInt(self.b[10:12])
        self.sectorsPerTrack = int(self.b[12])
        self.hardDiskParams = self.wordToInt(self.b[16:18])
        self.sectorsPerAU = int(self.hardDiskParams >> 12) + 1
        self.totalSectors = self.sectorsPerAU * self.totalAUs
        self.auSize = self.sectorsPerAU * self.sectorSize
        self.numberOfHeads = ((self.hardDiskParams >> 8) & 0x0f) + 1
        self.numberOfCylinders = self.totalSectors // (self.sectorsPerTrack * self.numberOfHeads)
        self.bufferedHeadStepping = bool(self.hardDiskParams & 0x80)
        self.writePrecompensation = int(self.hardDiskParams & 0x7f) * 16
        self.DSK1Emu = self.wordToInt(self.b[26:28])
        self.totalBytes = self.sectorSize * self.sectorsPerAU * self.totalAUs
        self.logicalMap = ['#'] * self.totalSectors
        self.ownerMap = [ None ] * self.totalSectors

        if (self.bsize < self.totalBytes):
            raise Exception('Disk file too small: Expected=' + str(self.totalBytes) + ' Actual=' + str(self.bsize))

        self.allocatedAUs = 0
        self.freeAUs = 0
        for i in range(0, self.totalAUs):
            if self.testBitmap(i):
                self.allocatedAUs += 1
                self.mapAU(i, TIUnknownAU(self, i))
            else:
                self.freeAUs += 1
                self.mapAU(i, TIFreeAU(self, i))

        # Note - everything above needs to happen first before super is called, because super will access the disk maps
        super().__init__(self, self, 0, self.b)

        # Fix the fields with different meanings in VIB vs DDR
        self.fullPath = self.name
        self.parentDDR = 0

        self.logicalMap[0] = 'V'
        self.ownerMap[0] = self
        for i in range(1, 32):
            self.logicalMap[i] = 'B'
            self.ownerMap[i] = TIVolumeBitmapAU(self, i // self.sectorsPerAU)
        for i in range(32, 64):
            self.logicalMap[i] = '.'
            self.ownerMap[i] = TIUnusedAU(self, i // self.sectorsPerAU)

        if (self.freeAUs + self.allocatedAUs != self.totalAUs):
            self.addWarning('Invalid Bitmap: Total=' + str(self.totalAUs) +
                            ' Allocated=' + str(self.allocatedAUs) +
                            ' Free=' + str(self.freeAUs))

        for i in range(0, 32 // self.sectorsPerAU):
            if (not self.testBitmap(i)):
                self.addWarning('Invalid Bitmap: VIB/ABM AU ' + str(i) + ' marked as free')


    def isValidAU(self, au):
        return ((au >= 0) and (au < self.totalAUs))

    def isValidSector(self, sector):
        return ((sector >= 0) and (sector < self.totalSectors))

    def isValidSectorOfAU(self, au, sector):
        return (self.isValidAU(au) and (sector >= 0) and (sector < self.sectorsPerAU))

    def testBitmap(self, au):
        return bool((self.b[au // 8 + self.sectorSize] >> (7 - (au % 8))) & 0x01)

    def setBitmap(self, au, used):
        if used:
            self.b[au // 8 + self.sectorSize] |= (1 << (7 - (au % 8)))
        else:
            self.b[au // 8 + self.sectorSize] &= ~(1 << (7 - (au % 8)))

    def mapAU(self, au, obj):
        if (obj is None):
            obj = TIUnusedAU(self, au)

        self.mapSectorOfAU(au, 0, obj)

        if (obj.mapType == 'D' or obj.mapType == 'I' or obj.mapType == 'F'):
            # Additional sectors in the AU are unused for DDIR, FDIR, and FDR
            obj = TIUnusedAU(self, au)
        for i in range(1, self.sectorsPerAU):
            self.mapSectorOfAU(au, i, obj)

    def mapSectorOfAU(self, au, sectorOffset, obj):
        if (obj is None):
            obj = TIUnusedAU(self, au)

        sector = au * self.sectorsPerAU + sectorOffset
        oldType = self.logicalMap[sector]
        oldOwner = self.ownerMap[sector]
        if ((oldType != '#') and (oldType != '?') and (oldType != ' ') and ((oldType != obj.mapType) or (oldOwner.au != obj.au))):
            self.addGlobalError(self,
                                'remapped sector ' + str(sector) + ' from ' + oldType + ' for ' + oldOwner.type +
                                ' ' + str(oldOwner.au) + ' (' + oldOwner.fullPath + ') to ' + obj.mapType +
                                ' for ' + obj.type + ' ' + str(obj.au) + ' (' + obj.fullPath + ')')

        self.logicalMap[sector] = obj.mapType
        self.ownerMap[sector] = obj

    def getSector(self, sector):
        i = sector * self.sectorSize
        return self.b[i:i+self.sectorSize]

    def getSectorOfAU(self, au, sectorOffset):
        i = au * self.auSize + sectorOffset * self.sectorSize
        return self.b[i:i+self.sectorSize]

    def getAU(self, au):
        i = au * self.auSize
        return self.b[i:i+self.auSize]

    def findPossibleBadSectors(self):
        badSectors = []
        for sector in range(0, self.totalSectors):
            sectorType = self.logicalMap[sector]
            if ((sectorType != '.') and (sectorType != ' ')):
                for pattern in [0xe5e5, 0xdead, 0xd7a5]:
                    if (self.doesSectorHaveBadDataPattern(sector, pattern)):
                        badSectors.append(sector)
                        break
        return badSectors

    def doesSectorHaveBadDataPattern(self, sector, pattern):
        start = sector * self.sectorSize
        end = start + self.sectorSize
        for i in range(start, end, 2):
            if (self.wordToInt(self.b[i:i+2]) != pattern):
                return False
        return True

    def addGlobalError(self, obj, error):
        self.addGlobalMessage(self.globalErrors, obj, error)

    def addGlobalWarning(self, obj, warning):
        self.addGlobalMessage(self.globalWarnings, obj, warning)

    def addGlobalMessage(self, dict, obj, msg):
        if (obj in dict):
            dict[obj].append(msg)
        else:
            dict[obj] = [msg]

    def printGlobalErrors(self, prefix=''):
        self.printGlobalMessages(self.globalErrors, prefix)

    def printGlobalWarnings(self, prefix=''):
        self.printGlobalMessages(self.globalWarnings, prefix)

    def printGlobalMessages(self, dict, prefix=''):
        for obj in dict:
            msgs = dict[obj]
            print(prefix + obj.type.ljust(6) + str(obj.sectorAddress) + '  ' + obj.fullPath)
            for msg in msgs:
                print(prefix + '  ' + msg)

    def printVals(self, includeFiles=False, includeSubdirs=False, prefix=''):
        self.printVal(prefix + 'Volume Name:', self.name)
        self.printVal(prefix + 'Size:', str(round(self.totalBytes / 1024 / 1024, 2)) + ' MB')
        self.printVal(prefix + 'Sectors:', self.totalSectors)
        self.printVal(prefix + 'Total AUs', self.totalAUs)
        self.printVal(prefix + 'Allocated AUs',
                      str(self.allocatedAUs) + ' (' + str(round(self.allocatedAUs / self.totalAUs * 100)) + '%)')
        self.printVal(prefix + 'Free AUs',
                      str(self.freeAUs) + ' (' + str(round(self.freeAUs / self.totalAUs * 100)) + '%)')
        self.printVal(prefix + 'Sectors/Track:', self.sectorsPerTrack)
        self.printVal(prefix + 'Sectors/AU:', self.sectorsPerAU)
        self.printVal(prefix + 'Heads:', self.numberOfHeads)
        self.printVal(prefix + 'Cylinders:', self.numberOfCylinders)
        self.printVal(prefix + 'Buffered Head Stepping:', self.bufferedHeadStepping)
        self.printVal(prefix + 'Write Pre-compensation:', self.writePrecompensation)
        self.printVal(prefix + 'DSK1 Emulation File AU:', self.DSK1Emu)
        print()
        super().printVals(includeFiles, includeSubdirs, prefix)

    def printSector(self, sector, prefix=''):
        owner = self.ownerMap[sector]
        print(prefix + owner.type.ljust(6) + str(owner.sectorAddress) + '  ' + owner.fullPath)
        sectorBytes = self.getSector(sector)
        for i in range(0, self.sectorSize, 16):
            sb = hex(i).lstrip('0x').zfill(4) + '  '
            sa = ' '
            for j in range(i, i+16):
                v = sectorBytes[j]
                sb += hex(v).lstrip('0x').zfill(2) + ' '
                if ((v >= 32) and (v < 127)):
                    sa += chr(v)
                else:
                    sa += '.'
            print(prefix + '  ' + sb + sa)


# Sectors 64 and up contain FDRs, FDIRs, DDRs, and file data


args = len(sys.argv)
if args < 2 or args > 4:
    print('usage: tidisk.py diskimage [badList] [exportDir]')
    sys.exit(1)

disk = TIDisk(bytearray(open(sys.argv[1], 'rb').read()))
disk.printVals(True, True)

print()
print('Logical Map:')
print(''.join(disk.logicalMap))

print()
print('Disk Tree:')
disk.printTree()

print()
print('Unknown Allocated Sectors:')
for i in range(0, disk.totalSectors):
    if (disk.logicalMap[i] == '?'):
        disk.printSector(i, '  ')

print()
print('Sectors not in tree with possible FDR or DDR:')
for i in range(0, disk.totalSectors):
    if (disk.logicalMap[i] != 'F' and disk.logicalMap[i] != 'D'):
        sectorBytes = disk.getSector(i)
        if (disk.isValidName(sectorBytes[0:10], True)):
            if (disk.bytesToString(sectorBytes[13:16]) == 'DIR' or disk.bytesToString(sectorBytes[28:30]) == 'FI' or
                    (sectorBytes[28] == 0 and sectorBytes[29] == 0)):
                disk.printSector(i, '  ')

print()
print('ERRORS:')
disk.printGlobalErrors('  ')

print()
print('WARNINGS:')
disk.printGlobalWarnings('  ')


if (args >= 3 and sys.argv[2] != ''):
    f = open(sys.argv[2], 'r')
    badList = f.readlines()
    f.close()
    badSectors = []
    for bad in badList:
        if (bad.startswith('Bad sectors on cylinder ')):
            s = bad.split()
            cyl = int(s[4])
            head = int(s[6].split(':')[0])
            for sector in s[7:]:
                badSectors.append(TISectorAddress(disk, cyl, head, int(sector.replace('H', ''))))

    print()
    print('Known Bad Sectors:')
    for badSector in badSectors:
        owner = disk.ownerMap[badSector.logicalSector]
        print('  ' + str(badSector) + ' (0x' +
              hex(disk.wordToInt(disk.getSector(badSector.logicalSector))).lstrip('0x').zfill(4) +
              ') mapped to ' + owner.type.ljust(5) + str(owner.au).rjust(5) + ' ' + owner.fullPath)


if (args >= 4):
    disk.export(sys.argv[3])

print()
print('Possible Bad Sectors:')
for sector in disk.findPossibleBadSectors():
    owner = disk.ownerMap[sector]
    addr = TISectorAddress(disk, logicalSector=sector)
    print('  ' + str(addr) + ' (0x' + hex(disk.wordToInt(disk.getSector(sector))).lstrip('0x').zfill(4) +
          ') mapped to ' + owner.type.ljust(5) + str(owner.au).rjust(5) + ' ' + owner.fullPath)


sys.exit(0)


