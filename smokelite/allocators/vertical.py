import os
import numpy as np
import pandas as pd
import PseudoNetCDF as pnc


def add_pressure(
    va_df, ptop=5000., psfc=101325., sigmakey='Sigma', pressurekey='Pressure',
    inplace=True
):
    """
    Add a pressure variable based on a known top of atmosphere and surface

    Arguments
    ---------
    va_df : pd.DataFrame
        file must contain sigmakey
    sigmakey : str
        name of Sigma variable
    ptop : float
        top of atmosphere in pascals (e.g., 5000. or 10000.)
    psfc : float
        surface of the earth for approximation (e.g., 101325.)
    pressurekey : str
        Key to add pressure as
    inplace : bool
        add to va_df (or copy)

    Returns
    -------
    outf : pd.DataFrame
        same as va_df, but with Pressure

    Notes
    -----

    Older files likely use ptop = 10000., while newer ones may use 5000.
    """
    if inplace:
        outdf = va_df
    else:
        outdf = va_df.copy()
    outdf.loc[:, pressurekey] = outdf.loc[:, sigmakey] * (psfc - ptop) + ptop
    return outdf


def interp_va(
    va_df, vglvls, vgtop=5000., psfc=101325., metakeys=None, verbose=False
):
    """
    Interpolate vertical allcoation dataframe to new vglvls

    Arguments
    ---------
    va_df : pandas.DataFrame
        must contain Pressure values that are top of the level values
    vglvls : array-like
        VGLVLS values (edges) of layers. First value will be ignored
    vgtop : scalar
        VGTOP from IOAPI, which is top of atmosphere in Pascals
    psfc : scalar
        Pressure at the surface for calculation
    metakeys : list or None
        list of keys that should *not* be renormalized to 1 (default
        ['Sigma', 'Alt', 'L'])
    verbose : bool
        show warnings

    Returns
    out_df : pandas.DataFrame
        vertical allocation data consistent with vglvls
    """
    from collections import OrderedDict
    x = vglvls[1:]
    if metakeys is None:
        metakeys = ['Sigma', 'Alt', 'L']
    xp = (va_df.Pressure.values - vgtop) / (psfc - vgtop)

    if xp[-1] < xp[0]:
        xp = xp[::-1]
        invert = True
    else:
        invert = False
    out = OrderedDict()

    for key in va_df.columns:
        fp = va_df[key].values
        if invert:
            fp = fp[::-1]
        out[key] = np.interp(x, xp, fp, left=0)
        if key not in metakeys:
            out[key] /= out[key].sum()
        if verbose:
            print(key)
            print(xp)
            print(fp)
            print(out[key])

    outdf = pd.DataFrame.from_dict(out)
    outdf['Sigma'] = x
    return outdf


def dfmake3d(
    infile, va_df, frackey, sigmakey='Sigma',
    outpath=None, overwrite=False, **save_kwds
):
    """
    Thin wrapper on make3d

    Arguments
    ---------
    infile : PseudoNetCDFFile
        file with IOAPI structure
    va_df : pd.DataFrame
        has sigmakey and frackey
    frackey : str
        column with layer fractions, should sum to 1
    sigmakey : str
        column with top edge sigma values to be used for VGLVLS
    outpath : str or None
        if str, saves to disk and returns result of save
        if None, returns in-memory file
    overwrite : bool
        If True, remove outpath if it exists
    save_kwds : dict
        if outpath is str, then save_kwds are used for save call

    Returns
    -------
    outfile : PseudoNetCDFFile or handle
        Result of PseudoNetCDFFile.save
    """
    if outpath is not None and os.path.exists(outpath):
        if overwrite:
            os.remove(outpath)

    vglvls = np.append(1, va_df[sigmakey].values)
    outfile = make3d(infile, va_df[frackey].values, vglvls)
    if outpath is None:
        return outfile
    else:
        return outfile.save(outpath, **save_kwds)


def make3d(infile, layerfractions, vglvls):
    """
    Interpolate vertical allocation dataframe to new vglvls

    Arguments
    ---------
    infile : PseudoNetCDFFile
        file with IOAPI structure
    layerfractions : array
        layer fractions should have one dimension and sum to 1
    vglvls : array
        sigmatops are the top edge values to be used for VGLVLS

    Returns
    -------
    """
    nz = layerfractions.shape[0]
    outfile = infile.slice(LAY=[0]*nz)

    for key, var in outfile.variables.items():
        if key != 'TFLAG':
            var[:] *= layerfractions[None, :, None, None]
    outfile.VGLVLS = vglvls.astype('f')
    outfile.NLAYS = nz
    return outfile


class Vertical:
    def __init__(
        self, csvpath, outvglvls, outvgtop, read_kwds=None,
        pressurekey='Pressure', sigmakey='Sigma', csvvgtop=5000.,
        metakeys=None, psfc=101325., prune=True, verbose=0
    ):
        """
        Arguments
        ---------
        csvpath : str
            path to vertical allocation file. Each key represents a value to
            use as a fractional allocation to this level.
        outvglvls : array
            Has nz+1 values, which will match the output file. The top edges
            outvglvls[1:] will be use for interpolation
        outvgtop : float
            top of the model atmosphere for output
        pressurekey : str
            key in csv that holds or will hold Pressure
        sigmakey : str
            key in csv that holds sigma (sigma should be layer tops)
        csvvgtop : float
            top of the model atmosphere when deriving csv
        metakeys : list or None
            If None, defaults to ['Sigma', 'Alt', 'L', 'Pressure']
        psfc : float
            pressure in Pascals at the surface. Used for interpolation between
            sigma grids
        prune : bool
            remove unnecessary levels
        verbose : int
            count of verbosity level

        Returns
        -------
        """
        if read_kwds is None:
            read_kwds = dict(comment='#')
        self.pressurekey = pressurekey
        self.sigmakey = sigmakey
        self.verbose = verbose
        self.outvglvls = outvglvls
        self.outvgtop = outvgtop
        self.psfc = psfc

        self.indf = pd.read_csv(csvpath, **read_kwds)
        if metakeys is None:
            metakeys = [self.sigmakey, self.pressurekey, 'Alt', 'L']

        self.metakeys = metakeys

        if self.pressurekey not in self.indf.columns:
            add_pressure(
                self.indf, ptop=csvvgtop, psfc=psfc, sigmakey=sigmakey,
                pressurekey=pressurekey, inplace=True
            )

        outdf = interp_va(
            self.indf, outvglvls[1:], vgtop=outvgtop, psfc=psfc,
            metakeys=metakeys, verbose=self.verbose
        )
        outdf.loc[:, 'LAYER1'] = 0
        outdf.loc[0, 'LAYER1'] = 1
        layerused = outdf.drop(self.metakeys, axis=1).values.sum(1) > 0
        layerused[0] = True
        if not prune:
            layerused[:] = True
        self.outdf = outdf.loc[layerused]

    def allocate(self, infile, alloc_keys, outpath=None, save_kwds=None):
        """
        Arguments
        ---------
        infile : str or PseudoNetCDFFile
            file to allocate vertically
        alloc_keys : mappable  or str
            each key should exist in the vertical allocation file, and values
            should correspond to variables in the infile. If is a str, then
            all allocatable variables will be asisgned to that csv key.
        outpath : str or None
            path to save output
        save_kwds : mappable
            keywords for outf.save method

        Returns
        -------
        outf : PseudoNetCDFFile or PseudoNetCDFFile.save output
            Has each variable associated with a csv key in alloc_keys as a
            variable, where the old file has 1 layer, the new file has nz
            layers.
        """
        if save_kwds is None:
            save_kwds = dict(
                format='NETCDF4_CLASSIC', complevel=1,
                verbose=self.verbose
            )

        if isinstance(alloc_keys, str):
            alloc_keys = {alloc_keys: None}

        if isinstance(infile, str):
            infile = pnc.pncopen(infile, format='ioapi')

        all_keys = []
        for k, v in infile.variables.items():
            if 'LAY' in v.dimensions:
                all_keys.append(k)

        assigned_keys = []

        isnone = []
        for sector, varkeys in alloc_keys.items():
            if varkeys is None:
                isnone.append(sector)
            else:
                assigned_keys.extend(varkeys)

        unassigned_keys = list(set(all_keys).difference(assigned_keys))
        if len(isnone) > 1:
            raise ValueError(f'Can only have 1 None sector; got {isnone}')
        if len(isnone) == 1:
            alloc_keys[isnone[0]] = unassigned_keys

        sectorfiles = []
        for sector, varkeys in alloc_keys.items():
            layerfractions = self.outdf.loc[:, sector]
            sectorfile = make3d(
                infile.subset(varkeys), layerfractions, self.outvglvls
            )
            sectorfiles.append(sectorfile)

        outfile = sectorfiles[0].stack(sectorfiles[1:], stackdim='TSTEP')
        if outpath is not None:
            return outfile.save(outpath, **save_kwds)
        else:
            return outfile
