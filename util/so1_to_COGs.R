library(raster)
library(gdalUtils)
library(tidyverse)

data_folder <- 'D:/Documents and Settings/azvoleff/OneDrive - Conservation International Foundation/Data'

load_as_vrt <- function(folder, pattern, band=FALSE, raster=TRUE) {
    vrt_file <- tempfile(fileext='.vrt')
    files <- list.files(folder, pattern=pattern)
    if (length(files) == 0) {
        print('No files found')
        return(FALSE)
    }
    if (band) {
        gdalbuildvrt(paste0(folder, '/', files), vrt_file, b=band)
        r <- raster(vrt_file)
    } else {
        gdalbuildvrt(paste0(folder, '/', files), vrt_file)
        r <- stack(vrt_file)
    }
    if (raster) {
        return(r)
    } else {
        return(vrt_file)
    }
}

###############################################################################
### Degradation data

tic('outcome variables - prepping')

ldn_baseline <- load_as_vrt(file.path(data_folder, 'Degradation_Paper', 
                                      'GEE_Rasters'),
                            'ldn_baseline_2001_2015_250m_ha[-.0-9]*tif$')
NAvalue(ldn_baseline) <- -32768
names(ldn_baseline) <-c('baseline_deg',
                        'baseline_stable',
                        'baseline_imp',
                        'baseline_nodata')
crs(ldn_baseline) <- '+init=epsg:4326'

# Note that areas are in hectares * 100
ldn_progress <- load_as_vrt(file.path(data_folder, 'Degradation_Paper', 
                                      'GEE_Rasters'),
                            'ldn_progress_2015_2019_250m_ha[-.0-9]*tif$')
NAvalue(ldn_progress) <- -32768
names(ldn_progress) <-c('progress_deg',
                        'progress_stable',
                        'progress_imp',
                        'progress_nodata')
crs(ldn_progress) <- crs(ldn_baseline)


baseline_files <- list.files(file.path(data_folder, 'Degradation_Paper', 'GEE_Rasters'),
    'ldn_baseline_2001_2015_250m_ha[-.0-9]*tif$', full.names=TRUE)
progress_files <- list.files(file.path(data_folder, 'Degradation_Paper', 'GEE_Rasters'),
    'ldn_progress_2015_2019_250m_ha[-.0-9]*tif$', full.names=TRUE)

baseline_vrt_file <- tempfile(fileext='.vrt')
progress_vrt_file <- tempfile(fileext='.vrt')

gdalbuildvrt(baseline_files, baseline_vrt_file, a_srs=crs('+init=epsg:4326'))
gdalbuildvrt(progress_files, progress_vrt_file, a_srs=crs('+init=epsg:4326'))

gdalwarp(vrt_file, ecoregion_PA_tif, te=output_extent, ts=output_dim, 
         ot='Int16', t_srs=crs(ldn_progress),
         co=c('compress=LZW', 'BIGTIFF=YES'), 
             wo='NUM_THREADS=4', multi=TRUE, overwrite=TRUE)
gdalwarp(vrt_file, ecoregion_PA_tif, te=output_extent, ts=output_dim, 
         ot='Int16', t_srs=crs(ldn_progress),
         co=c('compress=LZW', 'BIGTIFF=YES'), 
             wo='NUM_THREADS=4', multi=TRUE, overwrite=TRUE)
